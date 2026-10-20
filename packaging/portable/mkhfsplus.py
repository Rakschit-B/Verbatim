"""Minimal mkfs.hfsplus: writes an empty, unjournaled HFS+ volume image (TN1150).

Usage: python mkhfsplus.py <image> <size_MB> <volume name>
Files are then added with libdmg-hfsplus `hfsplus <image> addall <dir>`.
"""
import struct
import sys
import time

BS = 4096          # allocation block size
NODE = 4096        # B-tree node size
HFS_EPOCH = 2082844800


def now():
    return int(time.time()) + HFS_EPOCH


def btree_header_node(total_nodes, max_key_len, btree_type, key_cmp, attrs, root=0, depth=0, leaf_records=0,
                      first_leaf=0, last_leaf=0, used_nodes=1):
    node = bytearray(NODE)
    # node descriptor: fLink, bLink, kind(1=header), height, numRecords(3), reserved
    struct.pack_into(">IIbBHH", node, 0, 0, 0, 1, 0, 3, 0)
    hdr = struct.pack(">HIIIIHHII", depth, root, leaf_records, first_leaf, last_leaf, NODE, max_key_len,
                      total_nodes, total_nodes - used_nodes)
    hdr += struct.pack(">HIBBI", 0, NODE, btree_type, key_cmp, attrs) + bytes(64)
    assert len(hdr) == 106
    node[14:14 + 106] = hdr
    # user data record 128 bytes at 120, map record from 248 to NODE - 8
    map_start, map_end = 248, NODE - 8
    for n in range(used_nodes):
        node[map_start + n // 8] |= 0x80 >> (n % 8)
    # record offsets (from end): rec0=14, rec1=120, rec2=248, free=map_end
    struct.pack_into(">HHHH", node, NODE - 8, map_end, map_start, 120, 14)
    return node


def uni(name):
    return struct.pack(">H", len(name)) + name.encode("utf-16-be")


def catalog_leaf(volname):
    t = now()
    node = bytearray(NODE)
    struct.pack_into(">IIbBHH", node, 0, 0, 0, -1, 1, 2, 0)
    # record 0: root folder (key parentID=1, name=volname)
    keydata = struct.pack(">I", 1) + uni(volname)
    key = struct.pack(">H", len(keydata)) + keydata
    perms = struct.pack(">IIBBHI", 0, 80, 0, 0, 0o040755, 0)  # owner root, group admin
    folder = struct.pack(">hHIIIIIII", 1, 0, 0, 2, t, t, t, t, 0) + perms + bytes(16) + bytes(16) + struct.pack(">II", 0, 0)
    assert len(folder) == 88, len(folder)
    rec0 = key + folder
    # record 1: root folder thread (key parentID=2, empty name)
    key1 = struct.pack(">HIH", 6, 2, 0)
    thread = struct.pack(">hhI", 3, 0, 1) + uni(volname)
    rec1 = key1 + thread
    off0 = 14
    off1 = off0 + len(rec0)
    if off1 % 2:
        off1 += 1
    node[off0:off0 + len(rec0)] = rec0
    node[off1:off1 + len(rec1)] = rec1
    free = off1 + len(rec1)
    struct.pack_into(">HHH", node, NODE - 6, free, off1, off0)
    return node


def fork(logical, start, blocks):
    return struct.pack(">QII", logical, BS, blocks) + struct.pack(">II", start, blocks) + bytes(8 * 7)


def make(path, size_mb, volname):
    total_blocks = size_mb * 1024 * 1024 // BS
    bitmap_blocks = (total_blocks + BS * 8 - 1) // (BS * 8)
    ext_nodes, cat_nodes, attr_nodes = 256, 16384, 256
    ext_blocks = ext_nodes * NODE // BS
    cat_blocks = cat_nodes * NODE // BS
    attr_blocks = attr_nodes * NODE // BS
    a_start = 1
    e_start = a_start + bitmap_blocks
    c_start = e_start + ext_blocks
    t_start = c_start + cat_blocks
    first_free = t_start + attr_blocks
    used = first_free + 1  # + last block (alternate header)
    with open(path, "wb") as f:
        f.truncate(total_blocks * BS)
        # allocation bitmap
        bm = bytearray(bitmap_blocks * BS)
        for b in list(range(first_free)) + [total_blocks - 1]:
            bm[b // 8] |= 0x80 >> (b % 8)
        f.seek(a_start * BS)
        f.write(bm)
        # extents overflow B-tree (empty)
        f.seek(e_start * BS)
        f.write(btree_header_node(ext_nodes, 10, 0, 0, 0x2))
        # catalog B-tree: header + one leaf (node 1)
        f.seek(c_start * BS)
        f.write(btree_header_node(cat_nodes, 516, 0, 0xCF, 0x6, root=1, depth=1, leaf_records=2, first_leaf=1,
                                  last_leaf=1, used_nodes=2))
        f.write(catalog_leaf(volname))
        # attributes B-tree (empty)
        f.seek(t_start * BS)
        f.write(btree_header_node(attr_nodes, 266, 0, 0, 0x6))
        t = now()
        vh = struct.pack(">2sHI4sIIIIIIIIIIIIIII", b"H+", 4, 0x100, b"10.0", 0, t, t, 0, t, 0, 0, BS, total_blocks,
                         total_blocks - used, first_free, 65536, 65536, 16, 1)
        vh += struct.pack(">Q", 1) + bytes(32)
        vh += fork(bitmap_blocks * BS, a_start, bitmap_blocks)
        vh += fork(ext_blocks * BS, e_start, ext_blocks)
        vh += fork(cat_blocks * BS, c_start, cat_blocks)
        vh += fork(attr_blocks * BS, t_start, attr_blocks)
        vh += bytes(80)  # startup file
        assert len(vh) == 512, len(vh)
        f.seek(1024)
        f.write(vh)
        f.seek(total_blocks * BS - 1024)
        f.write(vh)


if __name__ == "__main__":
    make(sys.argv[1], int(sys.argv[2]), sys.argv[3])
