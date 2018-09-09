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

        # > prediction_offset: download from accum_viewport, else download from viewport
        self.prediction_offset = 2

        self.bandwidth_manager = BandwidthManager(bandwidth_trace)
        self.buffer = Buffer()
        self.adaption = Name(self.buffer)

        self.playback_position = 0
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
                if playback_duration > segment.duration:
                    simprint(self, "%d: stalling happens during playback" % self.playback_position)
                simprint(self, "%d: watching" % self.playback_position)
                yield self.timeout(playback_duration)
                self.playback_position += 1
            else:
                try:
                    simprint(self, "%d: stalling -> no segment available" % self.playback_position)
                    self.playback_stalled = True
                    yield self.playback_sleep_event
                except simpy.Interrupt:
                    simprint(self, "segment available")
        simprint(self, "video completed")

    def download(self):
        download_index = 1

        # always download first segment in lowest quality:
        simprint(self, "starting download segment: %d" % download_index)
        segment = self.get_segment(0, 0)
        download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
        self.buffer.download_started(self.now, self.now + download_time, segment)
        self.wake_playback()
        yield self.timeout(download_time)

        while download_index < self.segment_count:
            representation, delay = self.adaption.get()
            simprint(self, "starting download segment: %d" % download_index)
            segment = self.get_segment(representation, download_index)
            download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
            yield self.timeout(delay)
            self.buffer.download_started(self.now, self.now + download_time, segment)
            self.wake_playback()
            yield self.timeout(download_time)

            yield self.timeout(1)

            download_index += 1

    def wake_playback(self):
        if self.playback_stalled:
            self.playback_stalled = False
            self.playback_process.interrupt("wake up")

    def get_segment(self, representation, index):
        return Segment(index, representation, self.get_segment_duration(index), [self.segment_sizes[index][representation]])


SimEnv([(0, 781250)],
       77,
       seminar.values.segment_sizes,
       seminar.values.deadlines,
       seminar.values.accum_viewport,
       seminar.values.example_viewport).run()
