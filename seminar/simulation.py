import simpy
from seminar.bandwidth import BandwidthManager
from seminar.segment import Segment
from seminar.adaption import Name, DualAdaption
from seminar.buffer import Buffer

import seminar.values

verbose = True


def simprint(env: simpy.Environment, msg: str):
    if verbose:
        print("%f: %s" % (env.now, msg))


class Download:
    def __init__(self, env: simpy.Environment, segment: Segment, bandwidth_manager: BandwidthManager, short: bool):
        self.env = env
        self.segment = segment
        self.bandwidth_manager = bandwidth_manager
        self.short = short

        self.hist = []

        self.download_start = 0
        self.download_time = 0
        self.remaining_bytes = segment.__len__()
        self.running = False
        self.running_time = 0
        self.queue_time = env.now

        self.sleep_event = env.event()
        self.process = env.process(self.download())

    def download(self):
        done = False
        while not done:
            try:
                if self.running:
                    yield self.env.timeout(self.download_time)
                    done = True
                else:
                    yield self.sleep_event
            except simpy.Interrupt:
                pass
        self.running = False
        self.running_time += self.env.now - self.download_start
        self.remaining_bytes = 0

    def progress(self, time):
        downloaded = 0
        for (downloaded_bytes, start, end) in self.hist:
            if start < time:
                if time >= end:
                    downloaded += downloaded_bytes
                else:
                    downloaded += downloaded_bytes * ((time - start) / (end - start))
        return downloaded / self.segment.__len__()

    def finished(self):
        return self.remaining_bytes == 0

    def average_bandwidth(self):
        return (self.segment.__len__() - self.remaining_bytes) / self.running_time

    def start(self):
        if not self.running and self.remaining_bytes > 0:
            self.download_start = self.env.now
            self.download_time = self.bandwidth_manager.get_download_time(self.env.now, self.remaining_bytes)
            self.hist.append((self.remaining_bytes, self.download_start, self.download_start + self.download_time))
            self.running = True
            self.process.interrupt("wake up")

    def pause(self):
        if self.running:
            simprint(self.env, "paused: %d" % self.segment.segment_index)
            if self.download_start < self.env.now:
                average_bandwidth = self.bandwidth_manager.get_average_bandwidth(self.download_start, self.env.now)
                self.remaining_bytes -= average_bandwidth * (self.env.now - self.download_start)
                assert self.remaining_bytes >= 0
                hist = self.hist[-1]
                self.hist[-1] = (hist[0] - self.remaining_bytes, hist[1], self.env.now)
            self.running = False
            self.running_time += self.env.now - self.download_start
            self.process.interrupt("sleep")


class DualBuffer:
    def __init__(self):
        self.short_segments = {}
        self.long_segments = {}
        self.playback = []

        # watched segments, short > long
        self.watched = []
        # combines short and long segment, if both are completely downloaded
        self.super_watched = []

    def download_short_segment(self, segment: Segment, download: Download):
        self.short_segments[segment.segment_index] = (segment, download)

    def download_long_segment(self, segment: Segment, download: Download):
        self.long_segments[segment.segment_index] = (segment, download)

    def playback_level(self, time):
        playback_level = 0
        for (playback_start, playback_finish, segment_duration) in self.playback:
            if playback_start < time:
                if playback_finish < time:
                    playback_level += segment_duration
                else:
                    playback_level += segment_duration * (
                            (time - playback_start) / (playback_finish - playback_start))
        return playback_level

    def buffer_level(self, time):
        buffer_level = 0
        for segment, download in self.long_segments.values():
            if download.queue_time < time:
                buffer_level += segment.duration * download.progress(time)
        return buffer_level - self.playback_level(time)

    def buffer_level_short(self, time):
        buffer_level = 0
        for segment, download in self.short_segments.values():
            if download.queue_time < time:
                buffer_level += segment.duration * download.progress(time)
        # print("buffer ", time, buffer_level, self.playback_level(time))
        return buffer_level - self.playback_level(time)

    def playback_available(self, index):
        return (index in self.short_segments and self.short_segments[index][1].finished()) or (
                index in self.long_segments and self.long_segments[index][1].finished())

    def playback_start_next(self, time, index) -> (Segment, float):
        if index in self.short_segments and self.short_segments[index][1].finished():
            segment, download = self.short_segments[index]
        else:
            segment, download = self.long_segments[index]
            if index not in self.short_segments:
                self.short_segments[index] = (segment, download)
        self.watched.append((time, segment, download))
        if index in self.short_segments and index in self.long_segments and self.short_segments[index][1].finished() and self.long_segments[index][1].finished():
            tmp = [short_tiles if short_tiles > long_tiles else long_tiles for short_tiles, long_tiles in zip(self.short_segments[index][0].tile_qualities, self.long_segments[index][0].tile_qualities)]
            self.super_watched.append(tmp)
        else:
            self.super_watched.append(segment.tile_qualities)
        tmp = (time, time + segment.duration, segment.duration)
        self.playback.append(tmp)
        return segment, segment.duration


class DownloadManager:
    def __init__(self, env: simpy.Environment, bandwidth_manager: BandwidthManager, buffer: DualBuffer):
        self.env = env
        self.bandwidth_manager = bandwidth_manager
        self.buffer = buffer

        self.terminated = False
        self.download_short = []
        self.download_long = []

        self.sleep_event = self.env.event()
        self.process = env.process(self.download())

    def download(self):
        simprint(self.env, "Download Manager started")
        while not self.terminated:
            try:
                if self.download_short.__len__() > 0:
                    self.download_short[0].start()
                    yield self.download_short[0].process
                    self.download_short.pop(0)
                elif self.download_long.__len__() > 0:
                    self.download_long[0].start()
                    yield self.download_long[0].process
                    self.download_long.pop(0)
                else:
                    yield self.sleep_event
            except simpy.Interrupt:
                pass
        simprint(self.env, "Download Manager terminated")

    def queue_download(self, segment: Segment, short: bool) -> simpy.Process:
        download = Download(self.env, segment, self.bandwidth_manager, short)
        if short:
            self.buffer.download_short_segment(segment, download)
            self.download_short.append(download)
            if self.download_long.__len__() > 0:
                self.download_long[0].pause()
        else:
            self.buffer.download_long_segment(segment, download)
            self.download_long.append(download)
        self.process.interrupt("new shit")
        return download.process

    def terminate(self):
        self.terminated = True
        self.process.interrupt("terminated")


class SimEnv(simpy.Environment):
    def __init__(self, short_factor, bandwidth_trace, segment_count, segment_sizes, deadlines, accum_viewport,
                 viewport):
        super(SimEnv, self).__init__()

        self.short_factor = short_factor

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
        self.buffer = DualBuffer()
        short_param = {"r": self.short_byte_rates,
                       "r_max": self.short_byte_rates.__len__() - 1,
                       "r_min": 0,
                       "b_min": 2,
                       "b_low": 3,
                       "b_high": 5}
        long_param = {"r": self.byte_rates,
                      "r_max": self.byte_rates.__len__() - 1,
                      "r_min": 0,
                      "b_min": self.threshold_short,
                      "b_low": 20,
                      "b_high": 50}
        self.adaption = DualAdaption(self.bandwidth_manager, self.buffer, self.short_factor, short_param, long_param)

        self.playback_position = 0
        self.playback_start_time = 0
        self.playback_finish_time = 0
        self.playback_stalled = False
        self.playback_sleep_event = self.event()

        self.q_threshold = 0.5
        self.starting_representation = 3
        self.download_short_index = 0
        self.download_long_index = 0

        self.download_manager = DownloadManager(self, self.bandwidth_manager, self.buffer)

        self.init_process = self.process(self.init_simulation())
        self.download_short_process = self.timeout(0)
        self.download_long_process = self.timeout(0)
        self.playback_process = None

        # self.download_process = self.process(self.download())
        # self.playback_process = self.process(self.playback())

    def init_simulation(self):
        if self.short_factor > 0:
            self.download_short_process = self.process(self.download_short())
            self.download_long_index = 3
        if self.short_factor < 1:
            self.download_long_process = self.process(self.download_long())
        self.playback_process = self.process(self.playback())
        yield self.download_short_process & self.download_long_process
        self.download_manager.terminate()

    def get_segment_duration(self, index):
        return self.deadlines[index + 1] - self.deadlines[index]

    def playback(self):
        while self.playback_position < self.segment_count:
            if self.buffer.playback_available(self.playback_position):
                segment, playback_duration = self.buffer.playback_start_next(self.now, self.playback_position)
                self.playback_start_time = self.now
                self.playback_finish_time = self.now + playback_duration
                simprint(self, "watching: %d" % self.playback_position)
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

    def download_short(self):
        last_download_index = 0
        simprint(self, "(short) queued download segment: %d" % self.download_short_index)
        segment = self.get_segment(self.starting_representation, self.download_short_index)
        yield self.download_manager.queue_download(segment, True)
        self.wake_playback()
        simprint(self, "(short) download finished: %d" % self.download_short_index)

        while self.download_short_index < self.segment_count - 1:
            representation, delay = self.adaption.get_short(last_download_index, self.now)
            if self.download_short_index <= self.playback_position:
                self.download_short_index = self.playback_position + 1
            else:
                self.download_short_index += 1
            segment = self.get_segment(representation, self.download_short_index)
            if self.download_short_index in self.buffer.long_segments and (representation == 0 or self.segment_quality_dif(segment, self.buffer.long_segments[self.download_short_index][0]) < self.q_threshold):
                yield self.timeout(delay)
                self.buffer.short_segments[self.download_short_index] = self.buffer.long_segments[self.download_short_index]
                simprint(self, "(short) moved segment: %d from long to short" % self.download_short_index)
                # yield self.timeout(self.segment_duration / 2)
            else:
                yield self.timeout(delay)
                simprint(self, "(short) queued download segment: %d; representation %d" % (
                    self.download_short_index, representation))
                yield self.download_manager.queue_download(segment, True)
                last_download_index = self.download_short_index
                simprint(self, "(short) download finished: %d" % self.download_short_index)
            self.wake_playback()

    def download_long(self):
        simprint(self, "(long) queued download segment: %d" % self.download_long_index)
        segment = self.get_segment(self.starting_representation, self.download_long_index)
        yield self.download_manager.queue_download(segment, False)
        self.wake_playback()
        simprint(self, "(long) download finished: %d" % self.download_long_index)

        while self.download_long_index < self.segment_count - 1:
            representation, delay = self.adaption.get_long(self.download_long_index, self.now)
            if self.download_long_index <= self.download_short_index:
                self.download_long_index = self.download_short_index + 1
            else:
                self.download_long_index += 1
            segment = self.get_accum_viewport_segment(representation, self.download_long_index)
            yield self.timeout(delay)
            simprint(self, "(long) queued download segment: %d; representation %d" % (
                self.download_long_index, representation))
            yield self.download_manager.queue_download(segment, False)
            simprint(self, "(long) download finished: %d" % self.download_long_index)
            self.wake_playback()

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
sim = SimEnv(0.5, bandwidth_trace,
             77,
             seminar.values.segment_sizes2,
             seminar.values.deadlines2,
             seminar.values.accum_viewport,
             seminar.values.example_viewport)
sim.run()

print(sim.adaption.short)
print(["short" if download.short else "long" for time, segment, download in sim.buffer.watched])


def get_segment_viewport_quality(viewport, buffer: dict):
    buffer_segments = [segment for segment, download in sorted(buffer.values(), key=lambda x: x[0].segment_index)]
    if buffer_segments.__len__() == 0:
        return -1
    count = 0
    quality = 0
    for tiles, segment in zip(viewport, buffer_segments):
        for viewport_tile, segment_tile in zip(tiles, segment.tile_qualities):
            if viewport_tile == 1:
                count += 1
                quality += segment_tile
    return quality / count


def get_super(viewport, segments_tiles: list):
    count = 0
    quality = 0
    for tiles, segment_tiles in zip(viewport, segments_tiles):
        for viewport_tile, segment_tile in zip(tiles, segment_tiles):
            if viewport_tile == 1:
                count += 1
                quality += segment_tile
    return quality / count


print(get_segment_viewport_quality(sim.viewport[4:], sim.buffer.long_segments))
print(get_segment_viewport_quality(sim.viewport[1:], sim.buffer.short_segments))
print(get_super(sim.viewport[1:], sim.buffer.super_watched))

