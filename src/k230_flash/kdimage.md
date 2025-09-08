# kdimage 格式介绍

本文档介绍 kdimage 文件格式及其在 Kendryte 烧录工具中的作用和实现细节，包括其文件结构、校验机制、解析流程以及 C++/Python 项目中的不同实现策略。

---

## 1. 概述

kdimage 是 Kendryte 烧录工具用于描述固件镜像的一种文件格式。该格式将固件固化为一个整体镜像文件，其中包含一个文件头和一个分区表（part table），以及多个分区（part）的实际数据。通过解析 kdimage 文件，可以验证数据完整性、提取各个固件分区，并在烧录过程中分别写入到目标介质中。

---

## 2. 文件结构

kdimage 文件主要由以下几个部分组成：

### 2.1. Image Header（512 字节）

文件头部大小固定为 512 字节，包含了镜像的元数据。

- **`img_hdr_magic` (uint32_t)**: Magic Number，固定为 `0x27CB8F93`，用于标识文件类型。
- **`img_hdr_crc32` (uint32_t)**: 对头部剩余部分（将本字段置零后）计算的 CRC32 校验和。
- **`img_hdr_flag` (uint32_t)**: 标志位，暂未使用。
- **`img_hdr_version` (uint32_t)**: 头部格式版本。**此版本号决定了后续分区表的解析方式**。
- **`part_tbl_num` (uint32_t)**: 分区表中包含的分区数量。
- **`part_tbl_crc32` (uint32_t)**: 对整个分区表数据计算的 CRC32 校验和。
- **`image_info`, `chip_info`, `board_info` (char[])**: 描述镜像、芯片、板卡信息的字符串。

### 2.2. Part Table（分区表）

紧跟在头部之后，由 `part_tbl_num` 个分区描述符组成。每个描述符占用 256 字节。

**版本兼容性**: 分区表的结构根据 `img_hdr_version` 的值有所不同。

- **版本 V1 (`img_hdr_version` < 2)**:
  - **`part_flag`** 字段为 **`uint32_t`** 类型。

- **版本 V2 (`img_hdr_version` >= 2)**:
  - **`part_flag`** 字段为 **`uint64_t`** 类型，提供了更强的扩展性。

**分区描述符 (`kd_img_part_t`) 核心字段**:

- **`part_magic` (uint32_t)**: 每个分区的 Magic Number，固定为 `0x91DF6DA4`。
- **`part_offset` (uint32_t)**: 分区在目标存储介质上的烧录起始地址。
- **`part_size` (uint32_t)**: 分区数据填充后的总大小（若 `part_content_size` 小于此值，剩余部分用 `0xFF` 填充）。
- **`part_erase_size` (uint32_t)**: 烧录前需要擦除的大小。
- **`part_max_size` (uint32_t)**: 分区在介质上占用的最大空间。
- **`part_content_offset` (uint32_t)**: 分区实际内容在 kdimage 文件中的偏移地址。
- **`part_content_size` (uint32_t)**: 分区实际内容的长度。
- **`part_content_sha256` (uint8_t[32])**: 分区实际内容（填充前）的 SHA-256 哈希值。
- **`part_name` (char[32])**: 分区名称字符串。

### 2.3. 分区内容数据

所有分区表之后，是各个分区紧密排列的实际数据。解析器根据每个分区描述符中的 `part_content_offset` 和 `part_content_size` 来定位和读取。

### 2.4. 文件结构示意图

```plaintext
+------------------------------+
|       kdimage 文件结构        |
+==============================+
|                              |
|  +------------------------+  |
|  |     Image Header       |  |
|  | (512 字节固定)         |  |
|  +------------------------+  |
|  | Magic: 0x27CB8F93      |  |  <-- 4字节 (uint32)
|  | CRC32 (头部置零后计算)   |  |  <-- 4字节 (uint32)
|  | header_flag            |  |  <-- 4字节 (uint32)
|  | header_version         |  |  <-- 4字节 (uint32)
|  | part_tbl_num           |  |  <-- 4字节 (uint32)
|  | part_tbl_crc32         |  |  <-- 4字节 (uint32)
|  | image_info (字符串)     |  |  <-- 32字节 (char[])
|  | chip_info (字符串)      |  |  <-- 32字节 (char[])
|  | board_info (字符串)     |  |  <-- 64字节 (char[])
|  | 保留字段               |  |  <-- 360字节 (填充至512字节)
|  +------------------------+  |
|                              |
|  +------------------------+  |
|  |       Part Table        |  |
|  | (n×256 字节，n≥1)      |  |
|  +------------------------+  |
|  | [Part 1]               |  |  <-- 256字节固定
|  | +--------------------+ |  |
|  | | Magic: 0x91DF6DA4  | |  |  <-- 4字节 (uint32)
|  | | part_offset        | |  |  <-- 4字节 (uint32)
|  | | part_size          | |  |  <-- 4字节 (uint32)
|  | | part_erase_size    | |  |  <-- 4字节 (uint32)
|  | | part_max_size      | |  |  <-- 4字节 (uint32)
|  | | part_flag          | |  |  <-- 4字节(V1) / 8字节(V2)
|  | | part_content_offset| |  |  <-- 4字节 (uint32)
|  | | part_content_size  | |  |  <-- 4字节 (uint32)
|  | | SHA-256 (32字节)    | |  |  <-- 32字节 (binary)
|  | | part_name (32字节)  | |  |  <-- 32字节 (char[])
|  | | 保留字段           | |  |  <-- 160字节(V1) / 156字节(V2)
|  | +--------------------+ |  |
|  |                        |  |
|  | [Part 2]               |  |  <-- 256字节固定
|  | ...                    |  |
|  +------------------------+  |
|                              |
|  +------------------------+  |
|  |      分区内容数据        |  |
|  +------------------------+  |
|  | [Part 1 数据]           |  |  <-- part_content_size字节
|  | (长度: part_content_size)| 
|  | 补0xFF至 part_size      |  |  <-- 填充到part_size大小
|  |                        |  |
|  | [Part 2 数据]           |  |
|  | ...                     |  |
|  +------------------------+  |
|                              |
+------------------------------+
```

---

## 3. 校验机制

kdimage 文件采用两种校验机制确保数据完整性：

- **CRC32 校验**:
  - **头部校验**: 验证 `kd_img_hdr_t` 自身的完整性。
  - **分区表校验**: 验证整个 Part Table 的完整性，防止分区描述被篡改。

- **SHA-256 校验**:
  - **分区内容校验**: 每个分区的数据在提取后都会计算 SHA-256 哈希，并与分区描述符中存储的值进行比对，确保分区内容在传输和存储过程中未损坏。

---

## 4. Python 模块接口

- **`get_kdimage_items(image_path)`**: 解析 kdimage 文件，并返回一个 `KburnImageItemList` 对象，包含所有分区的元数据。
- **`get_kdimage_max_offset(image_path)`**: 获取整个镜像中最大的偏移值，用于验证固件大小是否超出介质容量。
- **`KburnKdImage.read_part_data(item)`**: 根据分区元数据 `item`，从文件中读取并校验该分区的数据。
