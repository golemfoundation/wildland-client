/*
  Added as a valid system-level test case for cached backend(s)
  courtesy of pisajew (c)2021(r)™

  https://gitlab.com/wildland/wildland-client/-/issues/671
*/
#include <sys/types.h>
#include <fcntl.h>
#include <errno.h>
#include <dirent.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

int eh(const char *msg, int v) {
  if(v == -1) {
    perror(msg);
    exit(1);
  }
  return v;
}

int lookup_file(const char *file_path) {
  const char * fname = strrchr(file_path, '/') + 1;
  char *basedir = strndup(file_path, fname - file_path);
  int namelen = strlen(fname);
  DIR *dirp = opendir(basedir);
  free(basedir);
  struct dirent *ep;
  int ec = ENOENT;
  while((ep = readdir(dirp)) != NULL) {
    if(strcmp(ep->d_name, fname) == 0) {
      ec = 0;
      break;
    }
  }
  closedir(dirp);

  return ec;
}

int main(int argc, char *argv[]) {
  int fd;
  assert(lookup_file(argv[1]) == ENOENT);
  eh("open", fd = open(argv[1], O_RDWR | O_CREAT));
  close(fd);
  assert(lookup_file(argv[1]) == 0);
  eh("unlink", unlink(argv[1]));
  assert(lookup_file(argv[1]) == ENOENT);

  return 0;
}
/*
  Local Variables:
  compile-command: "cc -g -os3test -O0 s3test.c"
  End:
*/
