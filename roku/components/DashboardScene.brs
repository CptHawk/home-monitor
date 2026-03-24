sub Init()
    m.video = m.top.FindNode("gridVideo")
    m.video.EnableCookies()

    ' TODO: Update this URL to your server's address
    content = CreateObject("roSGNode", "ContentNode")
    content.url = "http://YOUR_SERVER_IP:8092/api/hls/grid.m3u8"
    content.streamformat = "hls"
    content.title = "Home Monitor"

    m.video.content = content
    m.video.control = "play"
    m.video.SetFocus(true)

    m.video.ObserveField("state", "onVideoState")
end sub

sub onVideoState()
    state = m.video.state
    if state = "error" or state = "finished"
        m.restartTimer = CreateObject("roSGNode", "Timer")
        m.restartTimer.repeat = false
        m.restartTimer.duration = 3
        m.restartTimer.ObserveField("fire", "onRestart")
        m.restartTimer.control = "start"
    end if
end sub

sub onRestart()
    content = CreateObject("roSGNode", "ContentNode")
    content.url = "http://YOUR_SERVER_IP:8092/api/hls/grid.m3u8"
    content.streamformat = "hls"
    content.title = "Home Monitor"
    m.video.content = content
    m.video.control = "play"
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    return true
end function
