/* Magpiary's hub launcher. launchd starts this small program inside a bundle named Magpiary, and it runs the hub
 * (`magpiary serve ...`, given as its arguments) as its child. macOS names the app responsible for a process in its
 * permission prompts, so they say "Magpiary" with its icon instead of "Python 3.12".
 * It forwards stop signals to the hub and ends with the hub's exit status; launchd restarts it as before.
 * Build: cc -O2 -o hub hub.c   (service.py builds it; the DMG build puts it in Magpiary.app) */
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void pass_on(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s program [arguments...]\n", argv[0]);
        return 64;
    }
    signal(SIGTERM, pass_on);
    signal(SIGINT, pass_on);
    signal(SIGHUP, pass_on);
    if (posix_spawn(&child, argv[1], NULL, NULL, &argv[1], environ) != 0) {
        perror("magpiary hub: could not start");
        return 70;
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return 70;  /* interrupted by a forwarded signal: keep waiting for the hub to finish */
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    return 128 + (WIFSIGNALED(status) ? WTERMSIG(status) : 0);
}
