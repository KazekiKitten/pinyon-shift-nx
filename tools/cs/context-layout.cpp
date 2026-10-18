// Host SDK layout only; no guest data. Both tested ABIs use this layout.
#include <rex/ppc/context.h>
#include <cstdio>
#include <cstddef>
int main() {
  std::printf("{\"size\":%zu,\"r3\":%zu,\"r0\":%zu,\"r1\":%zu,\"r2\":%zu,"
              "\"r4\":%zu,\"lr\":%zu,\"ctr\":%zu,\"cr0\":%zu,\"fpscr\":%zu,"
              "\"f0\":%zu,\"v0\":%zu}\n",
              sizeof(PPCContext), offsetof(PPCContext,r3), offsetof(PPCContext,r0),
              offsetof(PPCContext,r1), offsetof(PPCContext,r2), offsetof(PPCContext,r4),
              offsetof(PPCContext,lr), offsetof(PPCContext,ctr), offsetof(PPCContext,cr0),
              offsetof(PPCContext,fpscr), offsetof(PPCContext,f0), offsetof(PPCContext,v0));
}
