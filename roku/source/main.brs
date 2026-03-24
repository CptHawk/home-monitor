sub Main()
    screen = CreateObject("roSGScreen")
    m.port = CreateObject("roMessagePort")
    screen.SetMessagePort(m.port)
    scene = screen.CreateScene("DashboardScene")
    screen.Show()

    while true
        msg = Wait(0, m.port)
        if type(msg) = "roSGScreenEvent"
            if msg.IsScreenClosed()
                return
            end if
        end if
    end while
end sub

sub RunScreenSaver()
    Main()
end sub
