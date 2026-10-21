import sys
def varint(n):
    out=bytearray()
    while True:
        b=n&0x7f; n>>=7
        if n: out.append(b|0x80)
        else: out.append(b); return bytes(out)
def f(num, wt, p):
    k=varint((num<<3)|wt)
    return k+varint(len(p))+p if wt==2 else k+varint(p)
site=f(1,2,b"PRIVATE")
for d in ["localhost","local","lan","home.arpa","internal"]:
    site+=f(2,2,f(1,0,2)+f(2,2,d.encode()))
open(sys.argv[1],'wb').write(f(1,2,site)); print("ok")
