#ifndef ARCSECOND_COMPAT_REGEX_H
#define ARCSECOND_COMPAT_REGEX_H

#include <stddef.h>
#include <string.h>

typedef struct regex_t {
    const char *pattern;
    int cflags;
} regex_t;

typedef struct regmatch_t {
    long rm_so;
    long rm_eo;
} regmatch_t;

#define REG_EXTENDED 0x01
#define REG_ICASE 0x02
#define REG_NOSUB 0x04
#define REG_NEWLINE 0x08

#define REG_NOMATCH 1

/*
 * Minimal POSIX regex compatibility shim for Windows/MSVC builds.
 * This only supports a basic substring match and exists to satisfy
 * astrometry's build-time dependency on <regex.h>.
 */
static int regcomp(regex_t *preg, const char *pattern, int cflags) {
    if (!preg || !pattern) {
        return REG_NOMATCH;
    }
    preg->pattern = pattern;
    preg->cflags = cflags;
    return 0;
}

static int regexec(
    const regex_t *preg,
    const char *string,
    size_t nmatch,
    regmatch_t pmatch[],
    int eflags
) {
    const char *p;
    (void)eflags;

    if (!preg || !preg->pattern || !string) {
        return REG_NOMATCH;
    }

    p = strstr(string, preg->pattern);
    if (!p) {
        return REG_NOMATCH;
    }

    if (nmatch > 0 && pmatch) {
        pmatch[0].rm_so = (long)(p - string);
        pmatch[0].rm_eo = (long)(pmatch[0].rm_so + (long)strlen(preg->pattern));
    }
    return 0;
}

static size_t regerror(
    int errcode,
    const regex_t *preg,
    char *errbuf,
    size_t errbuf_size
) {
    const char *msg = (errcode == 0) ? "No error" : "No match";
    size_t len = strlen(msg);
    (void)preg;

    if (errbuf && errbuf_size > 0) {
        size_t copy_len = (len < (errbuf_size - 1)) ? len : (errbuf_size - 1);
        memcpy(errbuf, msg, copy_len);
        errbuf[copy_len] = '\0';
    }

    return len + 1;
}

static void regfree(regex_t *preg) {
    if (preg) {
        preg->pattern = NULL;
        preg->cflags = 0;
    }
}

#endif
