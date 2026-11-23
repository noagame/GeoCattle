#ifndef GEOCATTLE_GC_TRANSPORT_H
#define GEOCATTLE_GC_TRANSPORT_H

// Códec de trama C++14 portable. Todos los enteros son explícitamente little endian.
// El reensamblado es solo en RAM; la finalización no equivale a un acuse de base de datos.
#include <stddef.h>
#include <stdint.h>

namespace gc {
constexpr size_t HEADER_SIZE = 26;
constexpr size_t MAX_RF = 255;
constexpr size_t CHUNK = MAX_RF - HEADER_SIZE;
constexpr size_t MAX_BATCH = 1100;
constexpr uint8_t MAX_PARTS = (MAX_BATCH + CHUNK - 1) / CHUNK;
constexpr uint32_t REASSEMBLY_TTL_MS = 15000;
constexpr uint8_t BROADCAST = 255;

enum Kind : uint8_t { Beacon = 1, Data = 2, Ack = 3 };
enum AckStatus : uint8_t { Accepted = 0, Busy = 1, Loop = 2, BadBatch = 3 };
enum ReassemblyResult : uint8_t { Invalid, Incomplete, Complete };

struct Header {
  uint8_t kind = 0;
  uint8_t src = 0;
  uint8_t dst = 0;
  uint32_t boot = 0;
  uint32_t number = 0;
  uint8_t index = 0;
  uint8_t parts = 0;
  uint16_t total = 0;
  uint32_t checksum = 0;
  uint32_t elapsed_ms = 0;
};

// Los helpers requieren que los llamadores provean un puntero de tamaño adecuado.
constexpr uint16_t read16(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) |
         static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}
constexpr uint32_t read32(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) |
         (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) |
         (static_cast<uint32_t>(p[3]) << 24);
}
constexpr void write16(uint8_t* p, uint16_t v) {
  p[0] = static_cast<uint8_t>(v);
  p[1] = static_cast<uint8_t>(v >> 8);
}
constexpr void write32(uint8_t* p, uint32_t v) {
  for (size_t i = 0; i < 4; ++i) p[i] = static_cast<uint8_t>(v >> (8 * i));
}
constexpr uint32_t crc32(const uint8_t* data, size_t length) {
  uint32_t crc = 0xFFFFFFFFUL;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320UL : 0UL);
  }
  return crc ^ 0xFFFFFFFFUL;
}
constexpr uint8_t partCount(uint16_t total) {
  return (total == 0 || total > MAX_BATCH) ? 0 :
         static_cast<uint8_t>((total + CHUNK - 1) / CHUNK);
}
constexpr size_t expectedDataPartLen(uint16_t total, uint8_t index) {
  const uint8_t parts = partCount(total);
  if (parts == 0 || index >= parts) return 0;
  const size_t remaining = static_cast<size_t>(total) - static_cast<size_t>(index) * CHUNK;
  return remaining < CHUNK ? remaining : CHUNK;
}
constexpr bool validHeader(const Header& h) {
  if (h.src > 2) return false;
  if (h.kind == Beacon)
    return h.dst == BROADCAST && h.index == 0 && h.parts == 1 && h.total == 14;
  if (h.kind == Data)
    return h.src >= 1 && h.dst <= 2 && h.dst != h.src &&
           h.parts == partCount(h.total) && h.parts != 0 && h.index < h.parts;
  if (h.kind == Ack)
    return h.dst >= 1 && h.dst <= 2 && h.dst != h.src && h.total == 0 &&
           h.parts == 0 && h.index <= BadBatch;
  return false;
}
constexpr bool encodeHeader(const Header& h, uint8_t* out, size_t capacity) {
  if (out == nullptr || capacity < HEADER_SIZE || !validHeader(h)) return false;
  out[0] = 'G'; out[1] = 'C'; out[2] = 1; out[3] = h.kind;
  out[4] = h.src; out[5] = h.dst;
  write32(out + 6, h.boot); write32(out + 10, h.number);
  out[14] = h.index; out[15] = h.parts;
  write16(out + 16, h.total); write32(out + 18, h.checksum);
  write32(out + 22, h.elapsed_ms);
  return true;
}
// Decodifica SOLO la cabecera. Los llamadores deben verificar el tamaño del payload y el CRC del beacon.
constexpr bool decodeHeader(const uint8_t* frame, size_t length, Header& result) {
  if (frame == nullptr || length < HEADER_SIZE || frame[0] != 'G' ||
      frame[1] != 'C' || frame[2] != 1) return false;
  Header h{};
  h.kind = frame[3]; h.src = frame[4]; h.dst = frame[5];
  h.boot = read32(frame + 6); h.number = read32(frame + 10);
  h.index = frame[14]; h.parts = frame[15]; h.total = read16(frame + 16);
  h.checksum = read32(frame + 18); h.elapsed_ms = read32(frame + 22);
  if (!validHeader(h)) return false;
  result = h;
  return true;
}

class Reassembly {
 public:
  constexpr Reassembly() = default;

  // Los datos completos pertenecen a este objeto hasta clearCompleted().
  // Consúmelos y limpia inmediatamente antes de alimentar otro lote distinto.
  constexpr ReassemblyResult ingest(const Header& h, const uint8_t* payload,
                                    size_t length, uint32_t now) {
    expire(now);
    if (h.kind != Data || !validHeader(h) || payload == nullptr ||
        length != expectedDataPartLen(h.total, h.index)) return Invalid;
    int index = -1;
    for (int i = 0; i < 2; ++i) {
      if (slots_[i].used && sameKey(slots_[i].header, h)) { index = i; break; }
    }
    if (completed_ >= 0 && index != completed_) return Invalid;
    if (index >= 0 && (slots_[index].header.total != h.total ||
        slots_[index].header.parts != h.parts || slots_[index].header.checksum != h.checksum)) {
      release(index);
      return Invalid;
    }
    if (index < 0) {
      for (int i = 0; i < 2; ++i) if (!slots_[i].used) { index = i; break; }
      if (index < 0) return Invalid;
      slots_[index].used = true;
      slots_[index].header = h;
      slots_[index].first = now;
      slots_[index].mask = 0;
      slots_[index].maxElapsed = h.elapsed_ms;
    }
    Slot& slot = slots_[index];
    const size_t offset = static_cast<size_t>(h.index) * CHUNK;
    const uint8_t bit = static_cast<uint8_t>(1U << h.index);
    if (slot.mask & bit) {
      for (size_t i = 0; i < length; ++i) {
        if (slot.data[offset + i] != payload[i]) { release(index); return Invalid; }
      }
    } else {
      for (size_t i = 0; i < length; ++i) slot.data[offset + i] = payload[i];
      slot.mask = static_cast<uint8_t>(slot.mask | bit);
    }
    if (h.elapsed_ms > slot.maxElapsed) slot.maxElapsed = h.elapsed_ms;
    if (slot.mask != static_cast<uint8_t>((1U << h.parts) - 1U)) return Incomplete;
    if (crc32(slot.data, slot.header.total) != slot.header.checksum) {
      release(index);
      return Invalid;
    }
    completed_ = index;
    return Complete;
  }
  constexpr const uint8_t* completedData() const {
    return completed_ < 0 ? nullptr : slots_[completed_].data;
  }
  constexpr size_t completedSize() const {
    return completed_ < 0 ? 0 : slots_[completed_].header.total;
  }
  constexpr uint32_t completedElapsed() const {
    return completed_ < 0 ? 0 : slots_[completed_].maxElapsed;
  }
  constexpr void clearCompleted() {
    if (completed_ >= 0) release(completed_);
  }
  constexpr void expire(uint32_t now) {
    for (int i = 0; i < 2; ++i) {
      if (slots_[i].used && i != completed_ &&
          static_cast<uint32_t>(now - slots_[i].first) >= REASSEMBLY_TTL_MS)
        release(i);
    }
  }

 private:
  struct Slot {
    bool used = false;
    Header header{};
    uint32_t first = 0;
    uint32_t maxElapsed = 0;
    uint8_t mask = 0;
    uint8_t data[MAX_BATCH] = {};
  };
  Slot slots_[2]{};
  int completed_ = -1;
  static constexpr bool sameKey(const Header& a, const Header& b) {
    return a.src == b.src && a.dst == b.dst && a.boot == b.boot && a.number == b.number;
  }
  constexpr void release(int i) {
    slots_[i].used = false;
    slots_[i].mask = 0;
    if (completed_ == i) completed_ = -1;
  }
};
} // namespace gc
#endif
