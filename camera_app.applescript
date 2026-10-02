-- EqualEd Camera: opens the camera view in its own window (never part of the teacher dashboard).
set projectDir to (POSIX path of (path to home folder)) & "EqualEd"
set appState to (do shell script "pgrep -f 'EqualEd.app/Contents/MacOS/launcher' >/dev/null && echo yes || echo no")
set hostAddr to do shell script "ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo 127.0.0.1"
set camKey to do shell script "cat " & quoted form of (projectDir & "/student_token.txt")
set camURL to "http://" & hostAddr & ":8765/s/" & camKey & "/camera"
if appState is "no" then
	do shell script "open -a EqualEd"
	do shell script "for i in $(seq 1 60); do curl -s -m 1 -o /dev/null " & quoted form of camURL & " && exit 0; sleep 1; done; exit 0"
end if
tell application "Google Chrome"
	repeat with w in windows
		if (title of w) is "EqualEd Camera" then
			set index of w to 1
			activate
			return
		end if
	end repeat
end tell
do shell script "open -na 'Google Chrome' --args --app=" & quoted form of camURL & " --window-size=1180,760"
