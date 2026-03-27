sub Init()
    m.bg = m.top.FindNode("bg")
    m.weatherTemp = m.top.FindNode("weatherTemp")
    m.weatherDetails = m.top.FindNode("weatherDetails")
    m.thermostatTemp = m.top.FindNode("thermostatTemp")
    m.thermostatDetails = m.top.FindNode("thermostatDetails")
    m.sensorsInfo = m.top.FindNode("sensorsInfo")
    m.weatherHeader = m.top.FindNode("weatherHeader")
    m.thermostatHeader = m.top.FindNode("thermostatHeader")
    m.sensorsHeader = m.top.FindNode("sensorsHeader")
    m.helpText = m.top.FindNode("helpText")

    ' Section focus: 0=weather, 1=thermostat, 2=sensors
    m.focusedSection = 1

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

sub updateSectionHighlight()
    ' Highlight the focused section header, dim the others
    sections = [m.weatherHeader, m.thermostatHeader, m.sensorsHeader]
    colors = ["#4FC3F7", "#FFB74D", "#CE93D8"]
    dimColors = ["#2A6A8A", "#8A6030", "#6A4A70"]

    for i = 0 to sections.Count() - 1
        if i = m.focusedSection
            sections[i].color = colors[i]
            sections[i].text = "> " + sections[i].text.Replace("> ", "")
        else
            sections[i].color = dimColors[i]
            sections[i].text = sections[i].text.Replace("> ", "")
        end if
    end for

    ' Update help text based on focused section
    if m.focusedSection = 1
        m.helpText.text = "[Up/Down] Section  [Left/Right] Temp  [OK] Mode  [*] Hide"
    else
        m.helpText.text = "[Up/Down] Section  [*] Hide  [OK] Fullscreen  [Back] Grid"
    end if
end sub

function handleKey(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "up"
        if m.focusedSection > 0
            m.focusedSection = m.focusedSection - 1
            updateSectionHighlight()
        end if
        return true
    else if key = "down"
        if m.focusedSection < 2
            m.focusedSection = m.focusedSection + 1
            updateSectionHighlight()
        end if
        return true
    else if key = "right" and m.focusedSection = 1
        ' Increase thermostat setpoint
        return false ' Let DashboardScene handle the API call
    else if key = "left" and m.focusedSection = 1
        ' Decrease thermostat setpoint
        return false
    else if key = "OK" and m.focusedSection = 1
        ' Cycle thermostat mode
        return false
    end if

    return false
end function

function isThermostatFocused() as Boolean
    return m.focusedSection = 1
end function
