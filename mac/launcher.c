/* The signed app's executable. Notarization needs a signed program here, and a shell
   script can't carry the hardened runtime, so this only runs Resources/launcher.sh with
   the system's bash. Built for both Apple silicon and Intel, so an Intel Mac gets the
   script's explanation instead of "this app can't be opened". */
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char exe[PATH_MAX], real[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real) == NULL) {
        fprintf(stderr, "Customizable Transcriber: can't find its own location\n");
        return 1;
    }
    /* .../Contents/MacOS/<name> -> .../Contents/Resources/launcher.sh */
    char *macos = dirname(real);
    if (snprintf(script, sizeof script, "%s/../Resources/launcher.sh", macos) >= (int)sizeof script) {
        return 1;
    }
    execl("/bin/bash", "bash", script, (char *)NULL);
    perror("Customizable Transcriber: /bin/bash");
    return 1;
}
