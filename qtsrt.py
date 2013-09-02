#!/usr/bin/python
import BaseHTTPServer
import re
import struct
import urllib2
import urlparse

class Proxy(BaseHTTPServer.BaseHTTPRequestHandler):

    mp4URLToFileSize = {}
    mp4URLToMoovMetadata = {}
    fileURLsToSubtitles = {}

    def do_GET(self):

        # Print bytes range for debugging purpose
        if "range" in self.headers:
            print "Incoming request with range %s" % self.headers["range"]

        # Get mp4 and srt urls
        qs = re.sub("^/?\?", "", self.path)
        qsParams = urlparse.parse_qs(qs)
        mp4URL = qsParams["mp4"][0]
        srtURL = qsParams["srt"][0]
        
        # Get metadata from mp4 if necessary
        if mp4URL not in self.mp4URLToFileSize:
            self.mp4URLToFileSize[mp4URL] = self.getSizeOfURL(mp4URL)
        if mp4URL not in self.mp4URLToMoovMetadata:
            self.mp4URLToMoovMetadata[mp4URL] = self.getMoovAtURL(mp4URL)

        # Create subtitles track if necessary
        if mp4URL+srtURL not in self.fileURLsToSubtitles:
            sbtl = Subtitles(srtURL, self.mp4URLToFileSize[mp4URL])
            oldMoov = self.mp4URLToMoovMetadata[mp4URL]["data"]
            newMoov = struct.pack("!I", len(oldMoov)+len(sbtl.trak)) + "moov"
            newMoov += oldMoov[8:] + sbtl.trak
            self.fileURLsToSubtitles[mp4URL+srtURL] = sbtl
            self.mp4URLToMoovMetadata[mp4URL]["data"] =  newMoov
            
        # Send response code
        if "range" in self.headers:
            self.send_response(206)
        else:
            self.send_response(200)

        # Compute total size and bytes range
        size = self.mp4URLToFileSize[mp4URL] + len(self.fileURLsToSubtitles[mp4URL+srtURL].mdat) + len(self.mp4URLToMoovMetadata[mp4URL]["data"])
        start, end = self.getRangeWithSize(size)

        # Send headers
        self.send_header("Content-type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", 'bytes ' + str(start) + '-' + str(end - 1) + '/' + str(size))
        self.send_header("Content-Length", end - start)
        self.end_headers()

        # Send remote data
        if start < self.mp4URLToFileSize[mp4URL]:
            remoteEnd = min(end, self.mp4URLToFileSize[mp4URL])
            moovRef = self.mp4URLToMoovMetadata[mp4URL]["ref"]
            if start < moovRef and remoteEnd > moovRef:
                firstRemoteEnd = moovRef
                stream = self.openURLWithRange(mp4URL, start, firstRemoteEnd)
                self.sendDataInChunks(stream, start, firstRemoteEnd)
                stream.close()
                self.sendDataInChunks("free", 0, 4)
                start = moovRef+4
            stream = self.openURLWithRange(mp4URL, start, remoteEnd)
            self.sendDataInChunks(stream, start, remoteEnd)
            stream.close()

        # Send local data
        if end > self.mp4URLToFileSize[mp4URL]:
            localStart = max(start, self.mp4URLToFileSize[mp4URL]) - self.mp4URLToFileSize[mp4URL]
            localEnd = end - self.mp4URLToFileSize[mp4URL]
            localData = self.fileURLsToSubtitles[mp4URL+srtURL].mdat + self.mp4URLToMoovMetadata[mp4URL]["data"]
            data = localData[localStart:localEnd]
            self.wfile.write(data)

        self.wfile.close()

    def sendDataInChunks(self, data, start, end):
        chunk = 0x1000
        while chunk > 0:
            if start + chunk > end:
                chunk = end - start
            try:
                chunkData = data[start:start+chunk] if isinstance(data, str) else data.read(chunk)
                self.wfile.write(chunkData)
            except:
                break
            start += chunk

    def openURLWithRange(self, url, start, end):
        headers = {"Range": "bytes=%s-%s" % (start, end)}
        request = urllib2.Request(url, headers=headers)
        return urllib2.urlopen(request)

    def getSizeOfURL(self, url):
        stream = urllib2.urlopen(url)
        return int(stream.headers["content-length"])

    def getMoovAtURL(self, url):
        cursor = 0
        while True:
            stream = self.openURLWithRange(url, cursor, cursor+8)
            size = struct.unpack("!I", stream.read(4))[0]
            type = stream.read(4)
            if size == 1:
                stream = self.openURLWithRange(url, cursor+8, cursor+16)
                size = struct.unpack("!Q", stream.read(8))[0]
            if type == "moov":
                stream = self.openURLWithRange(url, cursor, cursor+size)
                return { "ref": cursor+4, "data": stream.read(size) }
            else:
                cursor += size

    def getRangeWithSize(self, size):
        start, end = 0, size
        if "range" in self.headers:
            s, e = self.headers['range'][6:].split('-', 1)
            sl = len(s)
            el = len(e)
            if sl > 0:
                start = int(s)
                if el > 0:
                    end = int(e) + 1
            elif el > 0:
                ei = int(e)
                if ei < size:
                    start = size - ei
        return (start, end)


class Subtitles(object):

    def __init__(self, url, offset):
        self.srt = urllib2.urlopen(url).read().replace("\r", "")
        self.parse(offset)

    def parse(self, offset):

        # Parse srt
        timePattern = "(\d{2}):(\d{2}):(\d{2}),(\d{3})"
        itemPattern = "\d+\n%s --> %s\n(.+?)\n\n" % (timePattern, timePattern)
        rawItems = re.findall(itemPattern, self.srt)
        
        # Convert items to convenient data structure
        items = []
        timeCursor = 0
        offsetCursor = offset+8
        for rawItem in rawItems:
            start = 3600000*int(rawItem[0])+60000*int(rawItem[1])+1000*int(rawItem[2])+int(rawItem[3])
            end = 3600000*int(rawItem[4])+60000*int(rawItem[5])+1000*int(rawItem[6])+int(rawItem[7])
            if start > timeCursor:
                items.append({ "offset": offsetCursor, "duration": start-timeCursor, "text": "" })
                offsetCursor += 2
            items.append({ "offset": offsetCursor, "duration": end-start, "text": rawItem[8] })
            timeCursor = end
            offsetCursor += 2+len(rawItem[8])

        # Create stsd
        stsd = struct.pack("!I", 0) + struct.pack("!I", 1)
        stsd += struct.pack("!I", 64) + "tx3g" + struct.pack("!H", 0)*3 + struct.pack("!H", 1)
        stsd += struct.pack("!I", 0) + struct.pack("!B", 1) + struct.pack("!b", -1) + struct.pack("!I", 0)
        stsd += struct.pack("!H", 0)*2 + struct.pack("!H", 36) + struct.pack("!H", 320)
        stsd += struct.pack("!I", 0) + struct.pack("!H", 1) + struct.pack("!B", 0) + struct.pack("!B", 12)
        stsd += struct.pack("!B", 255)*4
        stsd += struct.pack("!I", 18) + "ftab" + struct.pack("!H", 1)*2 + struct.pack("!B", 5) + "Arial"
        stsd = struct.pack("!I", 8+len(stsd)) + "stsd" + stsd

        # Create stts
        itemsPackedByDuration = []
        for item in items:
            if len(itemsPackedByDuration) == 0 or itemsPackedByDuration[-1][1] != item["duration"]:
                itemsPackedByDuration.append([1, item["duration"]])
            else:
                itemsPackedByDuration[-1][0] += 1
        stts = struct.pack("!I", 0) + struct.pack("!I", len(itemsPackedByDuration))
        for entry in itemsPackedByDuration:
            stts += struct.pack("!I", entry[0]) + struct.pack("!I", entry[1])
        stts = struct.pack("!I", 8+len(stts)) + "stts" + stts

        # Create stsz
        stsz = struct.pack("!I", 0)*2 + struct.pack("!I", len(items))
        for item in items:
            stsz += struct.pack("!I", 2+len(item["text"]))
        stsz = struct.pack("!I", 8+len(stsz)) + "stsz" + stsz

        # Create stsc
        stsc = struct.pack("!I", 0) + struct.pack("!I", 1)*4
        stsc = struct.pack("!I", 8+len(stsc)) + "stsc" + stsc

        # Create stco
        stco = struct.pack("!I", 0) + struct.pack("!I", len(items))
        for item in items:
            stco += struct.pack("!I", item["offset"])
        stco = struct.pack("!I", 8+len(stco)) + "stco" + stco

        # Create stbl
        stbl = stsd + stts + stsz + stsc + stco
        stbl = struct.pack("!I", 8+len(stbl)) + "stbl" + stbl

        # Create nmhd
        nmhd = struct.pack("!I", 12) + "nmhd" + struct.pack("!I", 0)

        # Create dinf
        dinf = struct.pack("!I", 12) + "url " + struct.pack("!I", 1)
        dinf = struct.pack("!I", 0) + struct.pack("!I", 1) + dinf
        dinf = struct.pack("!I", 8+len(dinf)) + "dref" + dinf
        dinf = struct.pack("!I", 8+len(dinf)) + "dinf" + dinf

        # Create minf
        minf = nmhd + dinf + stbl
        minf = struct.pack("!I", 8+len(minf)) + "minf" + minf

        # Create hdlr
        hdlr = struct.pack("!I", 0)*2 + "sbtl" + struct.pack("!I", 0)*4 + struct.pack("!B", 0)
        hdlr = struct.pack("!I", 8+len(hdlr)) + "hdlr" + hdlr

        # Create mdhd
        mdhd = struct.pack("!I", 0) + struct.pack("!I", 3450525113)*2 + struct.pack("!I", 1000)
        mdhd += struct.pack("!I", timeCursor) + struct.pack("!H", 5575) + struct.pack("!H", 0)
        mdhd = struct.pack("!I", 8+len(mdhd)) + "mdhd" + mdhd

        # Create mdia
        mdia = mdhd + hdlr + minf
        mdia = struct.pack("!I", 8+len(mdia)) + "mdia" + mdia

        # Create tkhd
        tkhd = struct.pack("!I", 3) + struct.pack("!I", 3450525113)*2 + struct.pack("!I", 3)
        tkhd += struct.pack("!I", 0) + struct.pack("!I", timeCursor) + struct.pack("!Q", 0)
        tkhd += struct.pack("!H", 65535) + struct.pack("!H", 2) + struct.pack("!H", 0)*2
        tkhd += struct.pack("!I", 65536) + struct.pack("!I", 0)*2
        tkhd += struct.pack("!I", 0) + struct.pack("!I", 65536) + struct.pack("!I", 0)
        tkhd += struct.pack("!I", 0) + struct.pack("!I", 13369344) + struct.pack("!I", 1073741824)
        tkhd += struct.pack("!I", 20971520)
        tkhd += struct.pack("!I", 2359296)
        tkhd = struct.pack("!I", 8+len(tkhd)) + "tkhd" + tkhd

        # Create trak
        self.trak = tkhd + mdia
        self.trak = struct.pack("!I", 8+len(self.trak)) + "trak" + self.trak

        # Create mdat
        self.mdat = ""
        for item in items:
            self.mdat += struct.pack("!H", len(item["text"])) + item["text"]
        self.mdat = struct.pack("!I", 8+len(self.mdat)) + "mdat" + self.mdat


if __name__ == "__main__":
    try:
        print "Starting server on port 8000"
        server  = BaseHTTPServer.HTTPServer(("", 8000), Proxy)
        server.serve_forever()
    except KeyboardInterrupt:
        print "Shutting down server"
        server.socket.close()