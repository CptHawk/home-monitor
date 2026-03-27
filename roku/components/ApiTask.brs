sub Init()
    m.top.functionName = "doRequest"
end sub

sub doRequest()
    url = m.top.requestUrl
    if url = "" or url = invalid then return

    request = CreateObject("roUrlTransfer")
    request.SetUrl(url)
    request.SetCertificatesFile("common:/certs/ca-bundle.crt")
    request.InitClientCertificates()

    port = CreateObject("roMessagePort")
    request.SetPort(port)

    if request.AsyncGetToString()
        msg = Wait(10000, port)
        if type(msg) = "roUrlEvent"
            code = msg.GetResponseCode()
            if code = 200
                body = msg.GetString()
                json = ParseJson(body)
                if json <> invalid
                    m.top.responseData = json
                end if
            end if
        end if
    end if
end sub
