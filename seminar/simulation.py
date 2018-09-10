import simpy
from seminar.bandwidth import BandwidthManager
from seminar.segment import Segment
from seminar.adaption import Name
from seminar.buffer import Buffer

import seminar.values

verbose = True


def simprint(env: simpy.Environment, msg: str):
    if verbose:
        print("%f: %s" % (env.now, msg))


class SimEnv(simpy.Environment):
    def __init__(self, bandwidth_trace, segment_count, segment_sizes, deadlines, accum_viewport, viewport):
        super(SimEnv, self).__init__()

        self.segment_count = segment_count
        self.segment_sizes = segment_sizes
        self.deadlines = deadlines
        self.accum_viewport = accum_viewport
        self.viewport = viewport

        # average byte size per quality
        self.representation_byte_rates = [0] * segment_sizes[0].__len__()
        for segment_size_per_quality in segment_sizes:
            for i, segment_size in enumerate(segment_size_per_quality, 0):
                self.representation_byte_rates[i] += segment_size / segment_count

        # > prediction_offset: download from accum_viewport, else download from viewport
        self.prediction_offset = 2

        self.bandwidth_manager = BandwidthManager(bandwidth_trace)
        self.buffer = Buffer()
        self.adaption = Name(self.buffer, self.representation_byte_rates)

        self.playback_position = 0
        self.playback_start_time = 0
        self.playback_finish_time = 0
        self.playback_stalled = False
        self.playback_sleep_event = self.event()

        self.download_process = self.process(self.download())
        self.playback_process = self.process(self.playback())

    def get_segment_duration(self, index):
        return self.deadlines[index + 1] - self.deadlines[index]

    def playback(self):
        while self.playback_position < self.segment_count:
            if self.buffer.playback_available(self.now, self.playback_position):
                segment, playback_duration = self.buffer.playback_start_next(self.now, self.playback_position)
                self.playback_start_time = self.now
                self.playback_finish_time = self.now + playback_duration
                if playback_duration > segment.duration:
                    simprint(self, "%d: stalling happens during playback" % self.playback_position)
                simprint(self, "%d: watching" % self.playback_position)
                self.playback_position += 1
                yield self.timeout(playback_duration)
            else:
                try:
                    simprint(self, "%d: stalling -> no segment available" % self.playback_position)
                    self.playback_stalled = True
                    yield self.playback_sleep_event
                except simpy.Interrupt:
                    simprint(self, "segment available")
        simprint(self, "video completed")

    def download(self):
        # always download first segment in lowest quality:
        simprint(self, "starting download segment: %d" % 0)
        segment = self.get_segment(3, 0)
        download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
        self.buffer.download_started(self.now, self.now + download_time, segment)
        self.wake_playback()
        yield self.timeout(download_time)

        download_index = 1
        while download_index < self.segment_count:
            representation, delay = self.adaption.get()
            simprint(self, "starting download segment: %d, representation: %d" % (download_index, representation))
            segment = self.get_segment(representation, download_index)
            download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
            # yield self.timeout(delay)
            self.buffer.download_started(self.now, self.now + download_time, segment)
            self.wake_playback()
            yield self.timeout(download_time)

            download_index += 1

    def wake_playback(self):
        if self.playback_stalled:
            self.playback_stalled = False
            self.playback_process.interrupt("wake up")

    def segment_quality_dif(self, segment_viewport: Segment, segment_accum_viewport: Segment) -> float:
        count = 0
        count_accum = 0
        for index, tile in enumerate(self.viewport[segment_viewport.segment_index], 0):
            if tile == 1:
                count += segment_viewport.tiles[index]
                count_accum += segment_accum_viewport.tiles[index]
        return count - count_accum

    def get_viewport_segment(self, max_byte, index):
        segment_sizes = self.segment_sizes[index]
        segment_viewport = self.viewport[index]
        count = 0
        for foo in segment_viewport:
            if foo == 1:
                count += 1
        low_quality_size = (segment_viewport.__len__() - count) * (self.representation_byte_rates[0] / 64)
        i = self.representation_byte_rates.__len__() - 1
        high_quality_size = count * (self.representation_byte_rates[i] / 64)
        while low_quality_size + high_quality_size > max_byte and i > 0:
            i -= 1
            high_quality_size = count * (self.representation_byte_rates[i] / 64)
        tmp = []
        for foo in segment_viewport:
            if foo == 1:
                tmp.append(high_quality_size / count)
            else:
                tmp.append(self.representation_byte_rates[0] / 64)
        return Segment(index, i, self.get_segment_duration(index), tmp)

    def get_segment(self, representation, index):
        return Segment(index, representation, self.get_segment_duration(index), [self.segment_sizes[index][representation] / 64] * 64)


SimEnv([(0, 781250)],
       77,
       seminar.values.segment_sizes2,
       seminar.values.deadlines2,
       seminar.values.accum_viewport,
       seminar.values.example_viewport).run()
