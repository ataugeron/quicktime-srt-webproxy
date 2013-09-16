quicktime-srt-webproxy
======================

Web proxy written in Python that combines two mp4 and srt files into a QuickTime video stream with a subtitle track.


How to use
======================

1. Start the server (run **qtsrt.py**).
2. Open **http://your-server-ip:8000?mp4=mp4-file-url&srt=srt-file-url** in a video player such as QuickTime or an iOS MPMoviePlayerController (don't forget to urlencode the mp4 and srt urls).

For more information
======================

* Checkout [my blog post](http://alexistaugeron.com/blog/2013/09/02/streaming-mp4-videos-plus-srt-subtitles-with-airplay/) about this project.
* If you want to learn more about how QuickTime files are structured, please take a look at the [QuickTime File Format Specification](https://developer.apple.com/library/mac/documentation/QuickTime/QTFF).
* Feel free to contact me if you need help understanding this code.