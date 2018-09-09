class Segment:
    # segment_index: which segment of the video
    # tiles: list, with byte size per tile
    def __init__(self, segment_index: int, representation: int, duration: float, tiles: list):
        self.segment_index = segment_index
        self.representation = representation
        self.duration = duration
        self.tiles = tiles

    def __len__(self):
        return sum(self.tiles)
