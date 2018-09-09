from seminar.bandwidth import BandwidthManager

bm = BandwidthManager([(0, 5000), (55, 2500), (60, 5000)])
print(bm.get_download_time(50, 50000))

