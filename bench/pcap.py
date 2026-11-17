"""Leest Modbus/TCP uit een pcap-bestand en maakt er transacties van, in de vorm die de benchmark gebruikt.

Alleen de standaardbibliotheek. Kent het klassieke pcap-formaat (wat tcpdump -w schrijft) met Ethernet of Linux
cooked capture, IPv4 en TCP. Een TCP-segment kan meer dan één Modbus-frame bevatten; een frame dat over twee segmenten
loopt, wordt overgeslagen (dat komt bij Modbus/TCP met korte verzoeken zelden voor).

Een transactie is één verzoek naar poort 502, met het antwoord erbij als dat in de opname zit:
    {"t": het moment in seconden (epoch, de klok van de opname), "src": client, "dst": server, "unit": unit id, "fc": function code,
     "addr": eerste register of coil, of null, "count": aantal, of null, "values": geschreven waarden, of null,
     "exception": de exceptioncode uit het antwoord, of null}
"""
import ipaddress
import struct

LINKTYPES = {1: 14, 113: 16, 276: 20}  # Ethernet, Linux cooked (SLL), SLL2: lengte van de kop
WRITE_CODES = (5, 6, 15, 16, 23)


def _packets(data):
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError("geen pcap-bestand (pcapng wordt niet gelezen; gebruik tcpdump -w)")
    nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    if linktype not in LINKTYPES:
        raise ValueError(f"linktype {linktype} wordt niet gelezen")
    offset = 24
    while offset + 16 <= len(data):
        sec, frac, caplen, _ = struct.unpack(endian + "IIII", data[offset:offset + 16])
        frame = data[offset + 16:offset + 16 + caplen]
        offset += 16 + caplen
        yield sec + frac / (1e9 if nano else 1e6), linktype, frame


def _segments(data):
    """(tijd, bron-ip, bronpoort, doel-ip, doelpoort, seq, payload) per TCP-segment met inhoud."""
    for t, linktype, frame in _packets(data):
        head = LINKTYPES[linktype]
        if linktype == 1:
            ethertype = struct.unpack(">H", frame[12:14])[0]
            if ethertype == 0x8100:  # VLAN-tag
                ethertype, head = struct.unpack(">H", frame[16:18])[0], 18
        elif linktype == 113:
            ethertype = struct.unpack(">H", frame[14:16])[0]
        else:
            ethertype = struct.unpack(">H", frame[0:2])[0]
        if ethertype != 0x0800:
            continue
        ip = frame[head:]
        if len(ip) < 20 or ip[9] != 6:
            continue
        ihl = (ip[0] & 0x0F) * 4
        total = struct.unpack(">H", ip[2:4])[0]
        tcp = ip[ihl:total]
        if len(tcp) < 20:
            continue
        sport, dport, seq = struct.unpack(">HHI", tcp[0:8])
        payload = tcp[(tcp[12] >> 4) * 4:]
        if payload:
            yield t, str(ipaddress.IPv4Address(ip[12:16])), sport, str(ipaddress.IPv4Address(ip[16:20])), dport, seq, payload


def _frames(payload):
    """De Modbus-frames in één TCP-payload: (transactie-id, unit, pdu)."""
    offset = 0
    while offset + 8 <= len(payload):
        tid, proto, length, unit = struct.unpack(">HHHB", payload[offset:offset + 7])
        if proto != 0 or length < 2 or offset + 6 + length > len(payload):
            return
        yield tid, unit, payload[offset + 7:offset + 6 + length]
        offset += 6 + length


def _request(pdu):
    fc, body = pdu[0], pdu[1:]
    addr = count = values = None
    try:
        if fc in (1, 2, 3, 4):
            addr, count = struct.unpack(">HH", body[:4])
        elif fc in (5, 6):
            addr, value = struct.unpack(">HH", body[:4])
            count, values = 1, [value]
        elif fc == 15:
            addr, count = struct.unpack(">HH", body[:4])
            bits = body[5:5 + body[4]]
            values = [(bits[i // 8] >> (i % 8)) & 1 for i in range(count)]
        elif fc == 16:
            addr, count = struct.unpack(">HH", body[:4])
            values = list(struct.unpack(f">{count}H", body[5:5 + 2 * count]))
        elif fc == 23:  # lezen en schrijven in één: het schrijfdeel telt voor het beleid
            _, _, addr, count = struct.unpack(">HHHH", body[:8])
            values = list(struct.unpack(f">{count}H", body[9:9 + 2 * count]))
    except (struct.error, IndexError):
        pass
    return fc, addr, count, values


def transactions(data, port=502):
    """Alle Modbus-verzoeken uit een pcap, met de exceptioncode uit het antwoord, gesorteerd op tijd."""
    requests, seen = {}, set()
    for t, src, sport, dst, dport, seq, payload in _segments(data):
        if (src, sport, dst, dport, seq) in seen:  # een herhaald segment (retransmissie)
            continue
        seen.add((src, sport, dst, dport, seq))
        for tid, unit, pdu in _frames(payload):
            if not pdu:
                continue
            if dport == port:
                fc, addr, count, values = _request(pdu)
                requests[(src, sport, dst, tid)] = {"t": round(t, 3), "src": src, "dst": dst, "unit": unit, "fc": fc,
                                                    "addr": addr, "count": count, "values": values, "exception": None}
            elif sport == port:
                request = requests.get((dst, dport, src, tid))
                if request is not None and pdu[0] & 0x80 and len(pdu) > 1:
                    request["exception"] = pdu[1]
    return sorted(requests.values(), key=lambda r: r["t"])
