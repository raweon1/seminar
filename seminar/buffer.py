from collections import defaultdict

from seminar.segment import Segment


class Buffer:
    def __init__(self):
        self.downloaded_segments = []
        self.extra_segments = {}
        self.playback = []

        self.playback_time = 0

    # return in seconds
    def buffer_level(self, time: float) -> float:
        sum_buffer_level = 0
        for (start, end, segment) in self.downloaded_segments:
            if start < time:
                if end < time:
                    sum_buffer_level += segment.duration
                else:
                    sum_buffer_level += segment.duration * ((time - start) / (end - start))
        sum_playback_time = 0
        for (playback_start, playback_finish, segment_duration) in self.playback:
            if playback_start < time:
                if playback_finish < time:
                    sum_playback_time += segment_duration
                else:
                    sum_playback_time += segment_duration * ((time - playback_start) / (playback_finish - playback_start))
        return sum_buffer_level - sum_playback_time

    def get_last_segment(self) -> Segment:
        return self.downloaded_segments[-1][2]

    def get_segment(self, index) -> Segment:
        return self.downloaded_segments[index][2]

    def playback_available(self, time, index):
        return index < self.downloaded_segments.__len__()

    def playback_start_next(self, time, index) -> (Segment, float):
        segment = self.get_segment(index)
        playback_duration = max(segment.duration, self.downloaded_segments[index][1] - time)
        tmp = (time, time + playback_duration, segment.duration)
        self.playback.append(tmp)
        return segment, playback_duration

    def download_started(self, start, end, segment: Segment):
        tmp = (start, end, segment)
        if segment.segment_index < self.downloaded_segments.__len__():
            self.extra_segments[segment.segment_index] = tmp
        else:
            self.downloaded_segments.append(tmp)

