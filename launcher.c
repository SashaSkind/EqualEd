/* EqualEd.app launcher: runs app.py with the project's Python, inside the app,
   so macOS grants camera and microphone access to "EqualEd". */
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <Python.h>
#ifndef PYHOME
#define PYHOME "/path/to/python3.11/home"  /* make_app.sh fills this in */
#endif
int main(int argc, char **argv){
  char root[4096];
#ifdef PROJECT_DIR
  snprintf(root, sizeof root, "%s", PROJECT_DIR);          /* app can live in /Applications */
#else
  char exe[4096]; uint32_t n = sizeof(exe); _NSGetExecutablePath(exe, &n);
  snprintf(root, sizeof root, "%s/../../..", dirname(exe)); /* app sits in the project folder */
#endif
  if (chdir(root) != 0) return 1;
  int fd = open("run.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); }
  setenv("PYTHONUNBUFFERED", "1", 1);
  setenv("PYTHONHOME", PYHOME, 1);
  setenv("PYTHONPATH", ".venv/lib/python3.11/site-packages", 1);
  char *args[] = {"python", "app.py", NULL};
  return Py_BytesMain(2, args);
}
