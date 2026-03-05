#ifndef ARCSECOND_COMPAT_SYS_PARAM_H
#define ARCSECOND_COMPAT_SYS_PARAM_H

#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif

#ifndef LITTLE_ENDIAN
#define LITTLE_ENDIAN 1234
#endif

#ifndef BIG_ENDIAN
#define BIG_ENDIAN 4321
#endif

#ifndef PDP_ENDIAN
#define PDP_ENDIAN 3412
#endif

#ifndef BYTE_ORDER
#define BYTE_ORDER LITTLE_ENDIAN
#endif

#ifndef PATH_MAX
#define PATH_MAX 260
#endif

#ifndef MAXPATHLEN
#define MAXPATHLEN PATH_MAX
#endif

#endif
