on run
    set projectPath to "/Users/dongxingxi/wechat-course-feedback"
    set appURL to "http://127.0.0.1:8765/"
    try
        do shell script "/usr/bin/curl -fsS --max-time 2 " & quoted form of (appURL & "api/state") & " >/dev/null"
    on error
        tell application "Terminal"
            do script "cd " & quoted form of projectPath & " && zsh start.command"
            activate
        end tell
        delay 2
    end try
    open location appURL
end run
