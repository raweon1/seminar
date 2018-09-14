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
        self.segment_duration = 2
        self.threshold_short = 5
        self.tile_count_short = 12

        # average byte / second per quality
        self.byte_rates = [0] * segment_sizes[0].__len__()
        for segment_size_per_quality in segment_sizes:
            for i, segment_size in enumerate(segment_size_per_quality, 0):
                self.byte_rates[i] += (segment_size / segment_count) / self.segment_duration  # duration

        # es werden max 12 tiles mit der representation runtergeladen,
        # alle anderen mit q0 -> normalisierung der byte rates
        byte_rate_0 = self.byte_rates[0] * ((self.tile_count - self.tile_count_short) / self.tile_count)
        self.short_byte_rates = [byte_rate * (self.tile_count_short / self.tile_count) + byte_rate_0 for byte_rate in
                                 self.byte_rates]

        self.bandwidth_manager = BandwidthManager(bandwidth_trace)
        self.buffer = Buffer()
        self.adaption = Name(self.buffer,
                             self.byte_rates,
                             self.threshold_short,
                             20,
                             50)

        self.buffer_short = Buffer()
        self.adaption_short = Name(self.buffer_short,
                                   self.short_byte_rates,
                                   1,
                                   3,
                                   5)

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
            if self.buffer_short.playback_available(self.now, self.playback_position):
                self.buffer.playback_start_next(self.now, self.playback_position)
                segment, playback_duration = self.buffer_short.playback_start_next(self.now, self.playback_position)
                self.playback_start_time = self.now
                self.playback_finish_time = self.now + playback_duration
                if playback_duration > segment.duration:
                    simprint(self, "%d: stalling happens during playback: %f seconds" % (self.playback_position, playback_duration - segment.duration))
                simprint(self, "%d: watching" % self.playback_position)
                self.playback_position += 1
                yield self.timeout(playback_duration)
            else:
                if self.buffer.playback_available(self.now, self.playback_position):
                    print(self.buffer.buffer_level(self.now), self.buffer_short.buffer_level(self.now))
                    segment = self.buffer.get_segment(self.playback_position)
                    self.buffer_short.download_started(-1000, self.now, segment)
                    print("yay")
                else:
                    try:
                        simprint(self, "%d: stalling -> no segment available" % self.playback_position)
                        self.playback_stalled = True
                        yield self.playback_sleep_event
                    except simpy.Interrupt:
                        simprint(self, "segment available")
        simprint(self, "video completed")

    def download(self):
        starting_representation = 3
        # always download first segment in lowest quality:
        simprint(self, "starting download segment: %d" % 0)
        segment = self.get_segment(starting_representation, 0)
        download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
        self.buffer_short.download_started(self.now, self.now + download_time, segment)
        self.buffer.download_started(self.now, self.now + download_time, segment)
        last_segment_throughput = (self.now, self.now + download_time)
        self.wake_playback()
        yield self.timeout(download_time)
        simprint(self, "finished download segment: %d, representation: %d" % (0, starting_representation))
        download_index_short = 1
        download_index_long = 1

        while download_index_short < self.segment_count:
            if download_index_short < self.playback_position:
                download_index_short = self.playback_position
                if download_index_long < download_index_short:
                    download_index_long = download_index_short
            if self.buffer.buffer_level(self.now) < self.threshold_short:
                representation, delay = self.adaption_short.get()
                segment = self.get_segment(representation, download_index_short)
                download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
                self.buffer_short.download_started(self.now, self.now + download_time, segment)
                self.buffer.download_started(self.now, self.now + download_time, segment)
                self.wake_playback()
                yield self.timeout(download_time)
                last_segment_throughput = download_time / segment.__len__()
                download_index_short += 1
                download_index_long = download_index_short
                print("downloaded buffer < threshold %d" % (download_index_short - 1))
            else:
                if self.buffer_short.buffer_level(self.now) < self.threshold_short:
                    simprint(self, "%f kkk" % self.buffer_short.buffer_level(self.now))
                    if self.buffer_short.buffer_level(self.now) > self.adaption_short.b_min:
                        representation, delay = self.adaption_short.get()
                        segment = self.get_segment(representation, download_index_short)
                        if self.segment_quality_dif(segment, self.buffer.get_segment(download_index_short)) > 1.5:
                            download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
                            self.buffer_short.download_started(self.now, self.now + download_time, segment)
                            self.wake_playback()
                            yield self.timeout(download_time)
                            last_segment_throughput = download_time / segment.__len__()
                            print("downloaded short %d" % (download_index_short))
                        else:
                            segment = self.buffer.get_segment(download_index_short)
                            download_time = last_segment_throughput * segment.__len__()
                            self.buffer_short.download_started(self.now - download_time, self.now, segment)
                            print("put long into short %d" % (download_index_short))
                            self.wake_playback()
                    else:
                        segment = self.buffer.get_segment(download_index_short)
                        download_time = last_segment_throughput * segment.__len__()
                        self.buffer_short.download_started(self.now - download_time, self.now, segment)
                        print("put long into short %d" % (download_index_short))
                        self.wake_playback()
                    simprint(self, "%f xxx" % self.buffer_short.buffer_level(self.now))
                    download_index_short += 1
                else:
                    if download_index_long < self.segment_count:
                        representation, delay = self.adaption.get()
                        yield self.timeout(delay)
                        segment = self.get_accum_viewport_segment(representation, download_index_long)
                        download_time = self.bandwidth_manager.get_download_time(self.now, segment.__len__())
                        self.buffer.download_started(self.now, self.now + download_time, segment)
                        yield self.timeout(download_time)
                        last_segment_throughput = download_time / segment.__len__()
                        download_index_long += 1
                        print("downloaded long %d" % (download_index_long - 1))
                    else:
                        yield self.timeout((self.buffer_short.buffer_level(self.now) - self.threshold_short) * 1.1)

    def wake_playback(self):
        if self.playback_stalled:
            self.playback_stalled = False
            self.playback_process.interrupt("wake up")

    @staticmethod
    def segment_quality_dif(segment_short: Segment, segment_long: Segment) -> float:
        quality = 0
        count = 0
        for tile_short, tile_long in zip(segment_short.tile_qualities, segment_long.tile_qualities):
            if tile_short > 0:
                count += 1
                quality += tile_short - tile_long
        return quality / count

    def get_accum_viewport_segment(self, representation, index):
        max_bytes = self.byte_rates[representation] * self.segment_duration
        segment_sizes = self.segment_sizes[index]
        segment_viewport = self.accum_viewport[index]
        accum_tile_sum = sum(segment_viewport)
        normalized_segment_viewport = [tile / accum_tile_sum for tile in segment_viewport]
        tile_qualities = []
        tiles = []
        for tile in normalized_segment_viewport:
            max_tile_byte = tile * max_bytes
            foo = tiles.__len__()
            for i, quality in reversed(list(enumerate(segment_sizes))):
                if max_tile_byte > quality / self.tile_count:
                    tile_qualities.append(i)
                    tiles.append(quality / self.tile_count)
                    break
            if foo == tiles.__len__():
                tile_qualities.append(0)
                tiles.append(segment_sizes[0] / self.tile_count)
        return Segment(index, representation, self.get_segment_duration(index), tiles, tile_qualities)

    def get_segment(self, representation, index) -> Segment:
        segment_sizes = self.segment_sizes[index]
        segment_viewport = self.viewport[index]
        tile_qualities = []
        tiles = []
        for tile in segment_viewport:
            if tile == 1:
                tile_qualities.append(representation)
                tiles.append(segment_sizes[representation] / self.tile_count)
            else:
                # tiles.append(segment_sizes[representation] / self.tile_count)
                tile_qualities.append(0)
                tiles.append(segment_sizes[0] / self.tile_count)
        return Segment(index, representation, self.get_segment_duration(index), tiles, tile_qualities)


# 781250 B/s , 6 MBit/s
# 6250000 B/s, 50 MBit/s
# 250000 B/s, 2 MBit/s
bandwidth = 781250
bandwidth_trace = [(i, bandwidth - ((781250 * 5 / 6) * (i / 200))) for i in range(0, 200)]
bandwidth_trace = [(0, bandwidth), (70, 0), (85, bandwidth / 2)]
print(bandwidth_trace)
sim = SimEnv(bandwidth_trace,
             77,
             seminar.values.segment_sizes2,
             seminar.values.deadlines2,
             seminar.values.accum_viewport,
             seminar.values.example_viewport)
sim.run()

print([sim.buffer_short.buffer_level(i) for i in range(0, 160)])
print([sim.buffer.buffer_level(i) for i in range(0, 160)])

print(sim.buffer_short.buffer_level(3.148428))
print(sim.buffer_short.buffer_level(3))


def get_segment_viewport_quality(viewport, buffer):
    buffer_segments = [segment for _, _, segment in buffer.downloaded_segments]
    count = 0
    quality = 0
    for tiles, segment in zip(viewport, buffer_segments):
        for viewport_tile, segment_tile in zip(tiles, segment.tile_qualities):
            if viewport_tile == 1:
                count += 1
                quality += segment_tile
    return quality / count


print(get_segment_viewport_quality(sim.viewport, sim.buffer_short))
print(get_segment_viewport_quality(sim.viewport, sim.buffer))
