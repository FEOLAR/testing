import ipaddress, sys
def varint(n):
    out=bytearray()
    while True:
        b=n&0x7f; n>>=7
        if n: out.append(b|0x80)
        else: out.append(b); return bytes(out)
def field(num, wt, payload):
    key=varint((num<<3)|wt)
    if wt==2: return key+varint(len(payload))+payload
    return key+varint(payload)
nets=[ipaddress.ip_network(l.strip(), strict=False) for l in open(sys.argv[1]) if l.strip() and not l.startswith('#')]
nets=list(ipaddress.collapse_addresses([n for n in nets if n.version==4]))+list(ipaddress.collapse_addresses([n for n in nets if n.version==6]))
geo=field(1,2,b"RU")
for n in nets:
    cidr=field(1,2,n.network_address.packed)+field(2,0,n.prefixlen)
    geo+=field(2,2,cidr)
data=field(1,2,geo)
open(sys.argv[2],'wb').write(data)
print(len(nets),"сетей,",len(data),"байт")
