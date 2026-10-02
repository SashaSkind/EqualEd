-- EqualEd Teacher: opens the EqualEd app window (Teacher tab). Starts EqualEd first if it is not running.
set projectDir to (POSIX path of (path to home folder)) & "EqualEd"
set appState to (do shell script "pgrep -f 'EqualEd.app/Contents/MacOS/launcher' >/dev/null && echo yes || echo no")
if appState is "no" then
	do shell script "open -a EqualEd"
else
	set hostAddr to do shell script "ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo 127.0.0.1"
	set appKey to do shell script "cat " & quoted form of (projectDir & "/student_token.txt")
	set appURL to "http://" & hostAddr & ":8765/s/" & appKey & "/app"
	do shell script "open -na 'Google Chrome' --args --app=" & quoted form of appURL & " --window-size=1440,920"
end if
