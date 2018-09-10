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

        self.tile_count = 64

        # average byte / second per quality
        self.representation_byte_rates = [0] * segment_sizes[0].__len__()
        for segment_size_per_quality in segment_sizes:
            for i, segment_size in enumerate(segment_size_per_quality, 0):
                self.representation_byte_rates[i] += (segment_size / segment_count) / 2  # duration
        # es werden max 12 tiles mit der representation runtergeladen, alle anderen mit q0 -> normalisierung der byte rates
        self.representation_byte_rates = [byte_rate * (12 / 64) + self.representation_byte_rates[0] * (52 / 64) for byte_rate in self.representation_byte_rates]

        self.bandwidth_manager = BandwidthManager(bandwidth_trace)
        self.buffer = Buffer()
        self.adaption = Name(self.buffer, self.representation_byte_rates, 0, 4, 6)

        self.buffer_long = Buffer()

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

        download_index_short = 1
        download_index_long = 1
        while download_index_short < self.segment_count:
            representation, delay = self.adaption.get()
            simprint(self, "starting download segment: %d, representation: %d" % (download_index_short, representation))
            segment = self.get_segment(representation, download_index_short)
            download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
            self.buffer.download_started(self.now, self.now + download_time, segment)
            self.wake_playback()
            yield self.timeout(download_time)
            download_index_short += 1
            download_index_long += 1
            simprint(self, "finished download segment: %d, representation: %d" % (download_index_short, representation))

            factor = 1
            while delay > 0 and download_index_long < self.segment_count:
                estimated_byte_count = delay * factor * self.adaption.average_throughput(self.now - self.adaption.delta_t, self.now)
                print(self.bandwidth_manager.get_download_time(self.now, self.get_accum_viewport_segment(estimated_byte_count, download_index_long).__len__()))
                print(delay)
                delay -= delay
                download_index_long += 1
                yield self.timeout(delay)

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

    def get_accum_viewport_segment(self, max_bytes, index):
        segment_sizes = self.segment_sizes[index]
        segment_viewport = self.accum_viewport[index]
        accum_tile_sum = sum(segment_viewport)
        normalized_segment_viewport = [tile / accum_tile_sum for tile in segment_viewport]

        foobar = []

        tiles = []
        for tile in normalized_segment_viewport:
            max_tile_byte = tile * max_bytes
            foo = tiles.__len__()
            for i, quality in reversed(list(enumerate(segment_sizes))):
                if max_tile_byte > quality / self.tile_count:
                    foobar.append(i)
                    tiles.append(quality / self.tile_count)
                    break
            if foo == tiles.__len__():
                foobar.append(0)
                tiles.append(segment_sizes[0] / self.tile_count)
        print(foobar, foobar.__len__())
        return Segment(index, -1, self.get_segment_duration(index), tiles)

    def get_segment(self, representation, index) -> Segment:
        segment_sizes = self.segment_sizes[index]
        segment_viewport = self.viewport[index]
        tiles = []
        for tile in segment_viewport:
            if tile == 1:
                tiles.append(segment_sizes[representation] / self.tile_count)
            else:
                # tiles.append(segment_sizes[representation] / self.tile_count)
                tiles.append(segment_sizes[0] / self.tile_count)
        return Segment(index, representation, self.get_segment_duration(index), tiles)


SimEnv([(0, 781250)],
       77,
       seminar.values.segment_sizes2,
       seminar.values.deadlines2,
       seminar.values.accum_viewport,
       seminar.values.example_viewport).run()
