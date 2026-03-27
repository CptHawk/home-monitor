sub Init()
    m.bg = m.top.FindNode("bg")
    m.weatherTemp = m.top.FindNode("weatherTemp")
    m.weatherDetails = m.top.FindNode("weatherDetails")
    m.thermostatTemp = m.top.FindNode("thermostatTemp")
    m.thermostatDetails = m.top.FindNode("thermostatDetails")
    m.lightsInfo = m.top.FindNode("lightsInfo")
    m.sensorsInfo = m.top.FindNode("sensorsInfo")
    m.weatherHeader = m.top.FindNode("weatherHeader")
    m.thermostatHeader = m.top.FindNode("thermostatHeader")
    m.lightsHeader = m.top.FindNode("lightsHeader")
    m.sensorsHeader = m.top.FindNode("sensorsHeader")
    m.helpText = m.top.FindNode("helpText")

    ' Section focus: 0=weather, 1=thermostat, 2=lights, 3=sensors
    m.focusedSection = 1
    ' Which light is selected within lights section
    m.focusedLight = 0
    m.lightDevices = []

    updateSectionHighlight()
end sub

sub onDataChanged()
    data = m.top.overlayData
    if data = invalid then return

    ' Weather
    weather = data.weather
    if weather <> invalid
        tempStr = ""
        if weather.temp_f <> invalid
            tempStr = Str(weather.temp_f).Trim() + Chr(176) + "F"
        end if
        m.weatherTemp.text = tempStr

        details = ""
        if weather.humidity <> invalid
            details = details + "Humidity: " + Str(weather.humidity).Trim() + "%"
        end if
        if weather.windSpeed <> invalid
            details = details + "  Wind: " + Str(weather.windSpeed).Trim() + " mph"
        end if
        if weather.condition <> invalid and weather.condition <> ""
            details = details + Chr(10) + weather.condition
        end if
        m.weatherDetails.text = details
    end if

    ' Thermostat
    therm = data.thermostat
    if therm <> invalid
        tempStr = ""
        if therm.temp_f <> invalid
            tempStr = Str(therm.temp_f).Trim() + Chr(176) + "F"
        end if
        m.thermostatTemp.text = tempStr

        details = ""
        if therm.mode <> invalid
            details = "Mode: " + therm.mode
        end if
        if therm.hvac_status <> invalid
            details = details + "  Status: " + therm.hvac_status
        end if
        if therm.heat_setpoint_c <> invalid
            setF = Int(therm.heat_setpoint_c * 9 / 5 + 32)
            details = details + Chr(10) + "Heat to: " + Str(setF).Trim() + Chr(176) + "F"
        end if
        if therm.cool_setpoint_c <> invalid
            setF = Int(therm.cool_setpoint_c * 9 / 5 + 32)
            details = details + "  Cool to: " + Str(setF).Trim() + Chr(176) + "F"
        end if
        m.thermostatDetails.text = details
    end if

    ' Lights
    lights = data.lights
    if lights <> invalid
        m.lightDevices = lights
        updateLightsDisplay()
    end if

    ' Sensors
    sensors = data.sensors
    if sensors <> invalid
        info = ""
        for each s in sensors
            name = s.name
            status = ""
            if s.doorOpen <> invalid
                if s.doorOpen
                    status = "OPEN"
                else
                    status = "Closed"
                end if
            end if
            if s.battery <> invalid
                status = status + "  Bat: " + Str(s.battery).Trim() + "%"
            end if
            if info <> "" then info = info + Chr(10)
            info = info + name + ": " + status
        end for
        m.sensorsInfo.text = info
    end if
end sub

sub updateLightsDisplay()
    info = ""
    for i = 0 to m.lightDevices.Count() - 1
        light = m.lightDevices[i]
        prefix = ""
        if m.focusedSection = 2 and i = m.focusedLight
            prefix = "> "
        end if

        status = light.power
        if light.canSetLevel and light.brightness <> invalid
            status = status + " " + Str(light.brightness).Trim() + "%"
        end if

        if info <> "" then info = info + Chr(10)
        info = info + prefix + light.name + ": " + status
    end for
    if info = "" then info = "No lights found"
    m.lightsInfo.text = info
end sub

sub updateSectionHighlight()
    ' Highlight the focused section header, dim the others
    sections = [m.weatherHeader, m.thermostatHeader, m.lightsHeader, m.sensorsHeader]
    colors = ["#4FC3F7", "#FFB74D", "#FFD54F", "#CE93D8"]
    dimColors = ["#2A6A8A", "#8A6030", "#8A7A30", "#6A4A70"]

    for i = 0 to sections.Count() - 1
        headerText = sections[i].text.Replace("> ", "")
        if i = m.focusedSection
            sections[i].color = colors[i]
            sections[i].text = "> " + headerText
        else
            sections[i].color = dimColors[i]
            sections[i].text = headerText
        end if
    end for

    ' Update help text based on focused section
    if m.focusedSection = 1
        m.helpText.text = "[Up/Dn] Section  [Lt/Rt] Temp  [OK] Mode  [*] Hide"
    else if m.focusedSection = 2
        m.helpText.text = "[Up/Dn] Light  [OK] Toggle  [Lt/Rt] Dim  [*] Hide"
    else
        m.helpText.text = "[Up/Dn] Section  [*] Hide  [OK] Fullscreen  [Back] Grid"
    end if

    ' Refresh lights display to show/hide selection arrows
    updateLightsDisplay()
end sub

function handleKey(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "up"
        if m.focusedSection = 2 and m.focusedLight > 0
            ' Navigate within lights list
            m.focusedLight = m.focusedLight - 1
            updateLightsDisplay()
            return true
        else if m.focusedSection > 0
            if m.focusedSection = 2
                ' Leaving lights section upward, reset light selection
                m.focusedLight = 0
            end if
            m.focusedSection = m.focusedSection - 1
            updateSectionHighlight()
        end if
        return true
    else if key = "down"
        if m.focusedSection = 2 and m.focusedLight < m.lightDevices.Count() - 1
            ' Navigate within lights list
            m.focusedLight = m.focusedLight + 1
            updateLightsDisplay()
            return true
        else if m.focusedSection < 3
            m.focusedSection = m.focusedSection + 1
            if m.focusedSection = 2
                m.focusedLight = 0
            end if
            updateSectionHighlight()
        end if
        return true
    else if m.focusedSection = 1
        ' Thermostat: left/right/OK handled by DashboardScene
        return false
    else if m.focusedSection = 2
        ' Lights: left/right/OK handled by DashboardScene
        return false
    end if

    return false
end function

function isThermostatFocused() as Boolean
    return m.focusedSection = 1
end function

function isLightsFocused() as Boolean
    return m.focusedSection = 2
end function

function getFocusedLightId() as String
    if m.focusedLight >= 0 and m.focusedLight < m.lightDevices.Count()
        return Str(m.lightDevices[m.focusedLight].id).Trim()
    end if
    return ""
end function

function getFocusedLightCanDim() as Boolean
    if m.focusedLight >= 0 and m.focusedLight < m.lightDevices.Count()
        return m.lightDevices[m.focusedLight].canSetLevel
    end if
    return false
end function
