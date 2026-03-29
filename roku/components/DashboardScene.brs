sub Init()
    ' Video setup
    m.video = m.top.FindNode("gridVideo")
    content = CreateObject("roSGNode", "ContentNode")
    ts = CreateObject("roDateTime")
    content.url = "http://YOUR_SERVER_IP:8092/api/hls/grid.m3u8?t=" + ts.AsSeconds().ToStr()
    content.streamformat = "hls"
    content.title = "Home Monitor"
    m.video.content = content
    m.video.control = "play"
    m.video.ObserveField("state", "onVideoState")

    ' Panel strip poster
    m.panelStrip = m.top.FindNode("panelStrip")

    ' Refresh timer (30 seconds)
    m.refreshTimer = m.top.FindNode("refreshTimer")
    m.refreshTimer.ObserveField("fire", "onRefreshTimer")
    m.refreshTimer.control = "start"

    m.top.SetFocus(true)
end sub

sub onRefreshTimer()
    ' Refresh panel strip with cache-busting timestamp
    ts = CreateObject("roDateTime")
    m.panelStrip.uri = "http://YOUR_SERVER_IP:8092/api/panel-strip.png?t=" + ts.AsSeconds().ToStr()
end sub

sub onVideoState()
    state = m.video.state
    if state = "error" or state = "finished"
        timer = CreateObject("roSGNode", "Timer")
        timer.duration = 3
        timer.repeat = false
        timer.ObserveField("fire", "onRestart")
        timer.control = "start"
        m.restartTimer = timer
    end if
end sub

sub onRestart()
    content = CreateObject("roSGNode", "ContentNode")
    ts = CreateObject("roDateTime")
    content.url = "http://YOUR_SERVER_IP:8092/api/hls/grid.m3u8?t=" + ts.AsSeconds().ToStr()
    content.streamformat = "hls"
    content.title = "Home Monitor"
    m.video.content = content
    m.video.control = "play"
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    return true
end function
