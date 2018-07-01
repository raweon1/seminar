from tmp import tmp, tmp_bandwidth


class BandwidthObserver:
    def bandwidth_changed(self, bandwidth_old: float):
        pass


class BandwidthObservable:
    def __init__(self):
        self.observer = []

    def register_observer(self, observer: BandwidthObserver):
        self.observer.append(observer)

    def remove_observer(self, observer: BandwidthObserver):
        self.observer.remove(observer)

    def notify_observer(self, bandwidth_old: float):
        pass


class Segment:
    def __init__(self, tile_count_x, tile_count_y, segment_time: float):
        # in seconds
        self.segment_time = segment_time
        # in Byte
        self.tile_size = [0 for _ in range(0, tile_count_x * tile_count_y)]
        self.tile_quality = [0 for _ in range(0, tile_count_x * tile_count_y)]
        self.tile_count_x = tile_count_x
        self.tile_count_y = tile_count_y

    def set_tile(self, x: int, y: int, size: int, quality: int):
        index = self.tile_count_x * x + y
        self.tile_size[index] = size
        self.tile_quality[index] = quality

    def __len__(self):
        return sum(self.tile_size)


class Environment(BandwidthObservable):
    def __init__(self, video_width: int, video_height: int, tile_count_x: int = 8, tile_count_y: int = 8):
        super(Environment, self).__init__()

        self.data = dict()

        # in seconds
        self.simulation_time = 0

        self.video_w = video_width
        self.video_h = video_height
        self.tile_x = tile_count_x
        self.tile_y = tile_count_y
        self.tile_count = self.tile_x * self.tile_y

        self.tile_matrix = [[]]
        self.segment_deadlines = []
        self.segment_index = 0

        # (time[seconds], bandwidth[byte/second])
        # gibt an, wie sich die Bandbreite im Laufe der Zeit entwickelt
        self.bandwidth_trace = []
        self.bandwidth_index = 0
        self.bandwidth = 0

    def get_next_segment(self) -> Segment or None:
        self.segment_index += 1
        if self.segment_deadlines.__len__() > self.segment_index:
            segment = Segment(self.tile_x, self.tile_y, self.segment_deadlines[self.segment_index])
            for i in range(0, self.tile_x):
                for j in range(0, self.tile_y):
                    segment.set_tile(i, j, int(self.tile_matrix[self.segment_index][0] / (self.tile_x * self.tile_y)),
                                     self.tile_matrix[0].__len__())
            return segment
        else:
            return None

    def change_bandwidth(self) -> bool:
        bandwidth_old = self.bandwidth
        self.bandwidth = self.bandwidth_trace[self.bandwidth_index][1]
        self.bandwidth_index += 1
        self.notify_observer(bandwidth_old)
        return self.bandwidth_trace.__len__() > self.bandwidth_index

    def notify_observer(self, bandwidth_old: float):
        for observer in self.observer:
            observer.bandwidth_changed(bandwidth_old)


class Event:
    def __init__(self, execution_time: float, environment: Environment):
        self.execution_time = execution_time
        self.environment = environment

    def execute_event(self) -> []:
        if self.execution_time < self.environment.simulation_time:
            raise RuntimeError("Event is happening in the past")
        else:
            self.environment.simulation_time = self.execution_time
        return self.action()

    def action(self) -> []:
        return []


class ChangeBandwidthEvent(Event):
    def __init__(self, execution_time: float, environment: Environment):
        super(ChangeBandwidthEvent, self).__init__(execution_time, environment)

    def action(self):
        if self.environment.change_bandwidth():
            return [ChangeBandwidthEvent(self.environment.bandwidth_trace[self.environment.bandwidth_index][0],
                                         self.environment)]
        else:
            return []


class DownloadEvent(Event, BandwidthObserver):
    def __init__(self, execution_time: float, environment: Environment, segment: Segment):
        super(DownloadEvent, self).__init__(execution_time, environment)
        self.start_time = environment.simulation_time
        self.last_time = environment.simulation_time
        self.segment = segment
        self.byte_downloaded = 0

    def action(self):
        # mean_bandwidth = self.segment.__len__() / (self.execution_time - self.start_time)
        next_segment = self.environment.get_next_segment()
        if next_segment is not None:
            next_execution_time = self.environment.simulation_time + (next_segment.__len__() / self.environment.bandwidth)
            return [DownloadEvent(next_execution_time, self.environment, next_segment)]
        else:
            return []

    def bandwidth_changed(self, bandwidth_old: float):
        self.byte_downloaded += (self.environment.simulation_time - self.last_time) * bandwidth_old
        self.last_time = self.environment.simulation_time
        bytes_left = self.segment.__len__() - self.byte_downloaded
        if bytes_left > 0:
            self.execution_time = self.environment.simulation_time + (bytes_left / self.environment.bandwidth)
        else:
            raise RuntimeError("Download already finished")


env = Environment(0, 0)
env.tile_matrix = tmp
env.segment_deadlines = [5.3 for _ in env.tile_matrix]
env.bandwidth_trace = tmp_bandwidth
env.bandwidth = tmp_bandwidth[0][1]
segment = env.get_next_segment()
event_list = [DownloadEvent(segment.__len__() / env.bandwidth, env, segment)]
count = 1
while event_list.__len__() > 0:
    event = sorted(event_list, key=lambda event: event.execution_time)[0]
    event_list.remove(event)
    event_list.extend(event.execute_event())
    count += 1
print(count)
print(env.simulation_time)
