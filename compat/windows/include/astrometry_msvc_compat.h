#ifndef ARCSECOND_COMPAT_ASTROMETRY_MSVC_COMPAT_H
#define ARCSECOND_COMPAT_ASTROMETRY_MSVC_COMPAT_H

/*
 * Force-included compatibility macros for building the upstream
 * astrometry C sources with MSVC.
 */
#if defined(_MSC_VER)

#ifndef __func__
#define __func__ __FUNCTION__
#endif

#ifndef __attribute__
#define __attribute__(x)
#endif

/*
 * astrometry's keywords.h does not define these for non-GNU compilers.
 * Keep them empty so declarations like "Pure InlineDeclare ..." parse.
 */
#ifndef InlineDeclare
#define InlineDeclare
#endif

#ifndef InlineDefineH
#define InlineDefineH
#endif

#ifndef InlineDefineC
#define InlineDefineC
#endif

#ifndef restrict
#define restrict __restrict
#endif

#endif

#endif
