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
  char exe[4096]; uint32_t n=sizeof(exe); _NSGetExecutablePath(exe,&n);
  char *macos=dirname(exe); char root[4096];
  snprintf(root,sizeof root,"%s/../../..",macos);
  chdir(root);
  int fd=open("run.log",O_WRONLY|O_CREAT|O_APPEND,0644);
  if(fd>=0){dup2(fd,1);dup2(fd,2);}
  setenv("PYTHONUNBUFFERED","1",1);
  setenv("PYTHONHOME",PYHOME,1);
  /* use the venv's site-packages */
  setenv("PYTHONPATH",".venv/lib/python3.11/site-packages",1);
  char *args[]={"python","webcam_yolov9.py",NULL};
  return Py_BytesMain(2,args);
}
