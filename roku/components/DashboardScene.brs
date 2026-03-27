sub Init()
    ' --- UI nodes ---
    m.video = m.top.FindNode("gridVideo")
    m.video.EnableCookies()
    m.cameraLabel = m.top.FindNode("cameraLabel")
    m.cameraLabelBg = m.top.FindNode("cameraLabelBg")
    m.modeIndicator = m.top.FindNode("modeIndicator")
    m.modeIndicatorBg = m.top.FindNode("modeIndicatorBg")
    m.helpToast = m.top.FindNode("helpToast")
    m.helpToastBg = m.top.FindNode("helpToastBg")
    m.infoOverlay = m.top.FindNode("infoOverlay")

    ' --- State ---
    ' TODO: Update this to your server's address
    m.serverBase = "http://YOUR_SERVER_IP:8092"
    m.cameras = []
    m.gridUrl = m.serverBase + "/api/hls/grid.m3u8"
    m.currentCamera = 0      ' Index into m.cameras
    m.isFullscreen = false    ' true = single camera, false = grid
    m.overlayVisible = false
    m.thermostatModes = ["HEAT", "COOL", "OFF"]
    m.currentThermostatMode = ""

    ' --- Start with grid stream ---
    playStream(m.gridUrl, "Grid View")
    m.video.SetFocus(true)

    ' --- Fetch config (camera list) ---
    fetchConfig()

    ' --- Fetch overlay data ---
    fetchOverlayData()

    ' --- Auto-refresh overlay data every 60 seconds ---
    m.refreshTimer = CreateObject("roSGNode", "Timer")
    m.refreshTimer.repeat = true
    m.refreshTimer.duration = 60
    m.refreshTimer.ObserveField("fire", "onRefreshTimer")
    m.refreshTimer.control = "start"

    ' --- Show help toast briefly on launch ---
    showHelpToast()

    ' --- Video error recovery ---
    m.video.ObserveField("state", "onVideoState")
end sub


' =========================================================================
' Stream playback
' =========================================================================

sub playStream(url as String, title as String)
    content = CreateObject("roSGNode", "ContentNode")
    content.url = url
    content.streamformat = "hls"
    content.title = title
    m.video.content = content
    m.video.control = "play"
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
    if m.isFullscreen and m.cameras.Count() > 0
        cam = m.cameras[m.currentCamera]
        playStream(cam.stream_url, cam.name)
    else
        playStream(m.gridUrl, "Grid View")
    end if
end sub


' =========================================================================
' API data fetching
' =========================================================================

sub fetchConfig()
    task = CreateObject("roSGNode", "ApiTask")
    task.ObserveField("responseData", "onConfigResponse")
    task.requestUrl = m.serverBase + "/api/roku/config"
    task.control = "run"
    m.configTask = task
end sub

sub onConfigResponse()
    data = m.configTask.responseData
    if data = invalid then return
    if data.grid_url <> invalid
        m.gridUrl = data.grid_url
    end if
    if data.cameras <> invalid
        m.cameras = data.cameras
    end if
end sub

sub fetchOverlayData()
    task = CreateObject("roSGNode", "ApiTask")
    task.ObserveField("responseData", "onOverlayResponse")
    task.requestUrl = m.serverBase + "/api/roku/overlay"
    task.control = "run"
    m.overlayTask = task
end sub

sub onOverlayResponse()
    data = m.overlayTask.responseData
    if data = invalid then return
    m.infoOverlay.overlayData = data
    if data.thermostat <> invalid and data.thermostat.mode <> invalid
        m.currentThermostatMode = data.thermostat.mode
    end if
end sub

sub onRefreshTimer()
    fetchOverlayData()
end sub


' =========================================================================
' Thermostat control API calls
' =========================================================================

sub adjustThermostat(deltaF as Integer)
    task = CreateObject("roSGNode", "ApiTask")
    task.ObserveField("responseData", "onThermostatAdjustResponse")
    task.requestUrl = m.serverBase + "/api/roku/thermostat/setpoint?delta_f=" + Str(deltaF).Trim()
    ' ApiTask uses GET; we need POST — use a dedicated approach
    m.thermostatTask = task
    doThermostatPost(m.serverBase + "/api/roku/thermostat/setpoint?delta_f=" + Str(deltaF).Trim())
end sub

sub setThermostatMode(mode as String)
    doThermostatPost(m.serverBase + "/api/roku/thermostat/mode?mode=" + mode)
end sub

sub doThermostatPost(url as String)
    ' Use roUrlTransfer directly for POST from render thread via task
    task = CreateObject("roSGNode", "PostTask")
    task.ObserveField("responseData", "onThermostatActionResponse")
    task.requestUrl = url
    task.control = "run"
    m.thermostatActionTask = task
end sub

sub onThermostatActionResponse()
    ' Refresh overlay data to show updated thermostat state
    fetchOverlayData()
end sub


' =========================================================================
' UI helpers
' =========================================================================

sub showHelpToast()
    m.helpToast.visible = true
    m.helpToastBg.visible = true
    m.hideHelpTimer = CreateObject("roSGNode", "Timer")
    m.hideHelpTimer.repeat = false
    m.hideHelpTimer.duration = 6
    m.hideHelpTimer.ObserveField("fire", "onHideHelpToast")
    m.hideHelpTimer.control = "start"
end sub

sub onHideHelpToast()
    m.helpToast.visible = false
    m.helpToastBg.visible = false
end sub

sub updateModeIndicator()
    if m.isFullscreen
        m.modeIndicator.text = "CAM " + Str(m.currentCamera + 1).Trim()
        m.modeIndicator.visible = true
        m.modeIndicatorBg.visible = true
    else
        m.modeIndicator.text = "GRID"
        m.modeIndicator.visible = true
        m.modeIndicatorBg.visible = true
    end if

    ' Auto-hide after 3 seconds
    m.hideModeTimer = CreateObject("roSGNode", "Timer")
    m.hideModeTimer.repeat = false
    m.hideModeTimer.duration = 3
    m.hideModeTimer.ObserveField("fire", "onHideModeIndicator")
    m.hideModeTimer.control = "start"
end sub

sub onHideModeIndicator()
    m.modeIndicator.visible = false
    m.modeIndicatorBg.visible = false
end sub

sub showCameraLabel(name as String)
    m.cameraLabel.text = name
    m.cameraLabel.visible = true
    m.cameraLabelBg.visible = true
end sub

sub hideCameraLabel()
    m.cameraLabel.visible = false
    m.cameraLabelBg.visible = false
end sub

sub switchToGrid()
    m.isFullscreen = false
    hideCameraLabel()
    playStream(m.gridUrl, "Grid View")
    updateModeIndicator()
end sub

sub switchToCamera(index as Integer)
    if m.cameras.Count() = 0 then return
    if index < 0 then index = m.cameras.Count() - 1
    if index >= m.cameras.Count() then index = 0
    m.currentCamera = index
    m.isFullscreen = true
    cam = m.cameras[m.currentCamera]
    playStream(cam.stream_url, cam.name)
    showCameraLabel(cam.name)
    updateModeIndicator()
end sub


' =========================================================================
' Remote control handler
' =========================================================================

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return true

    ' --- Info overlay toggle ---
    if key = "options"
        m.overlayVisible = not m.overlayVisible
        m.infoOverlay.visible = m.overlayVisible
        if m.overlayVisible
            fetchOverlayData()
        end if
        return true
    end if

    ' --- When overlay is visible, delegate navigation ---
    if m.overlayVisible
        handled = m.infoOverlay.callFunc("handleKey", key, press)
        if handled then return true

        ' Thermostat controls when thermostat section is focused
        isThermostat = m.infoOverlay.callFunc("isThermostatFocused")
        if isThermostat
            if key = "right"
                adjustThermostat(1)
                return true
            else if key = "left"
                adjustThermostat(-1)
                return true
            else if key = "OK"
                cycleThermostatMode()
                return true
            end if
        end if

        ' Back hides overlay
        if key = "back"
            m.overlayVisible = false
            m.infoOverlay.visible = false
            return true
        end if
    end if

    ' --- Camera/grid navigation (overlay not visible) ---
    if key = "OK"
        if not m.isFullscreen
            ' Enter fullscreen for current camera
            switchToCamera(m.currentCamera)
        else
            ' Return to grid
            switchToGrid()
        end if
        return true
    end if

    if key = "right"
        if m.isFullscreen
            switchToCamera(m.currentCamera + 1)
        else
            ' In grid mode, pre-select next camera
            if m.cameras.Count() > 0
                m.currentCamera = (m.currentCamera + 1) mod m.cameras.Count()
                flashCameraPreview()
            end if
        end if
        return true
    end if

    if key = "left"
        if m.isFullscreen
            switchToCamera(m.currentCamera - 1)
        else
            if m.cameras.Count() > 0
                m.currentCamera = m.currentCamera - 1
                if m.currentCamera < 0 then m.currentCamera = m.cameras.Count() - 1
                flashCameraPreview()
            end if
        end if
        return true
    end if

    if key = "back"
        if m.isFullscreen
            switchToGrid()
            return true
        end if
        ' In grid mode, don't consume back — let Roku handle exit
        return false
    end if

    if key = "play"
        if m.video.control = "play"
            m.video.control = "pause"
        else
            m.video.control = "play"
        end if
        return true
    end if

    ' Consume other keys to prevent Roku default behavior
    return true
end function

sub flashCameraPreview()
    ' Briefly show which camera is pre-selected while in grid mode
    if m.cameras.Count() > 0
        cam = m.cameras[m.currentCamera]
        showCameraLabel(">> " + cam.name)
        m.hidePreviewTimer = CreateObject("roSGNode", "Timer")
        m.hidePreviewTimer.repeat = false
        m.hidePreviewTimer.duration = 2
        m.hidePreviewTimer.ObserveField("fire", "onHidePreview")
        m.hidePreviewTimer.control = "start"
    end if
end sub

sub onHidePreview()
    if not m.isFullscreen
        hideCameraLabel()
    end if
end sub

sub cycleThermostatMode()
    ' Cycle through HEAT -> COOL -> OFF -> HEAT
    currentIdx = -1
    for i = 0 to m.thermostatModes.Count() - 1
        if m.thermostatModes[i] = m.currentThermostatMode
            currentIdx = i
            exit for
        end if
    end for
    nextIdx = (currentIdx + 1) mod m.thermostatModes.Count()
    newMode = m.thermostatModes[nextIdx]
    m.currentThermostatMode = newMode
    setThermostatMode(newMode)
end sub
