// Decodes the samples of an FMOD FSB4 bank from the player's own game files
// to 16-bit PCM WAV (#446): MPEG samples with FFmpeg's MP3 decoder, XMA ones
// with the SDK's XMA frame decoder (the one the game's audio runs on), PCM16
// as stored. One line of JSON per sample goes to stdout.
//
//   pinyon_shift_fh1_audio_decode <bank.fsb> <output folder> [--sample N]
//   pinyon_shift_fh1_audio_decode --list <bank.fsb>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

#include <rex/stream.h>

extern "C" {
#include <libavcodec/avcodec.h>
}

namespace {

constexpr uint32_t kModePcm16 = 0x00000010;
constexpr uint32_t kModeMpeg = 0x00000200;
constexpr uint32_t kModeXma = 0x01000000;
constexpr uint32_t kModeBigEndian = 0x08000000;
constexpr size_t kBankHeaderSize = 48;
constexpr size_t kSampleHeaderSize = 80;
constexpr size_t kDataAlign = 32;

struct Sample {
  uint32_t index = 0;
  std::string name;
  uint32_t length_samples = 0;
  uint32_t length_bytes = 0;
  uint32_t mode = 0;
  int32_t frequency = 0;
  uint16_t channels = 0;
  size_t offset = 0;
};

uint32_t U32(const uint8_t* p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
uint16_t U16(const uint8_t* p) { return uint16_t(p[0] | p[1] << 8); }

std::optional<std::vector<Sample>> ReadBank(const std::vector<uint8_t>& data, std::string& error) {
  if (data.size() < kBankHeaderSize || std::memcmp(data.data(), "FSB4", 4) != 0) {
    error = "not an FSB4 bank";
    return std::nullopt;
  }
  const uint32_t count = U32(&data[4]);
  const uint32_t header_size = U32(&data[8]);
  if (kBankHeaderSize + size_t(header_size) > data.size()) {
    error = "truncated sample headers";
    return std::nullopt;
  }
  std::vector<Sample> samples;
  size_t at = kBankHeaderSize;
  size_t offset = (kBankHeaderSize + header_size + kDataAlign - 1) & ~(kDataAlign - 1);
  for (uint32_t i = 0; i < count; ++i) {
    if (at + kSampleHeaderSize > kBankHeaderSize + header_size) {
      error = "sample header past the header block";
      return std::nullopt;
    }
    const uint8_t* h = &data[at];
    const uint16_t size = U16(h);
    if (size < kSampleHeaderSize) {
      error = "short sample header";
      return std::nullopt;
    }
    Sample sample;
    sample.index = i;
    sample.name.assign(reinterpret_cast<const char*>(h + 2), strnlen(reinterpret_cast<const char*>(h + 2), 30));
    sample.length_samples = U32(h + 32);
    sample.length_bytes = U32(h + 36);
    sample.mode = U32(h + 48);
    sample.frequency = int32_t(U32(h + 52));
    sample.channels = U16(h + 62);
    sample.offset = offset;
    if (offset + sample.length_bytes > data.size()) {
      error = "sample data past the end of the bank";
      return std::nullopt;
    }
    offset = (offset + sample.length_bytes + kDataAlign - 1) & ~(kDataAlign - 1);
    at += size;
    samples.push_back(std::move(sample));
  }
  return samples;
}

class Decoder {
 public:
  Decoder(AVCodecID id, int rate, int channels) {
    const AVCodec* codec = avcodec_find_decoder(id);
    if (!codec) return;
    context_ = avcodec_alloc_context3(codec);
    context_->sample_rate = rate;
    context_->channels = channels;
    if (id == AV_CODEC_ID_XMAFRAMES) context_->flags2 |= AV_CODEC_FLAG2_SKIP_MANUAL;
    if (avcodec_open2(context_, codec, nullptr) < 0) avcodec_free_context(&context_);
    frame_ = av_frame_alloc();
    packet_ = av_packet_alloc();
  }
  ~Decoder() {
    if (context_) avcodec_free_context(&context_);
    av_frame_free(&frame_);
    av_packet_free(&packet_);
  }
  bool ok() const { return context_ != nullptr; }

  // Decodes one packet, appending interleaved 16-bit samples.
  bool Decode(const uint8_t* data, size_t size, std::vector<int16_t>& out) {
    packet_->data = const_cast<uint8_t*>(data);
    packet_->size = int(size);
    if (avcodec_send_packet(context_, packet_) < 0) return false;
    while (avcodec_receive_frame(context_, frame_) == 0) {
      const int channels = context_->channels;
      for (int i = 0; i < frame_->nb_samples; ++i) {
        for (int c = 0; c < channels; ++c) {
          float v = 0.0f;
          if (frame_->format == AV_SAMPLE_FMT_FLTP) {
            v = reinterpret_cast<const float*>(frame_->extended_data[c])[i];
          } else if (frame_->format == AV_SAMPLE_FMT_FLT) {
            v = reinterpret_cast<const float*>(frame_->extended_data[0])[i * channels + c];
          } else if (frame_->format == AV_SAMPLE_FMT_S16P) {
            v = reinterpret_cast<const int16_t*>(frame_->extended_data[c])[i] / 32768.0f;
          } else if (frame_->format == AV_SAMPLE_FMT_S16) {
            v = reinterpret_cast<const int16_t*>(frame_->extended_data[0])[i * channels + c] /
                32768.0f;
          }
          out.push_back(int16_t(std::clamp(v, -1.0f, 1.0f) * 32767.0f));
        }
      }
    }
    return true;
  }

 private:
  AVCodecContext* context_ = nullptr;
  AVFrame* frame_ = nullptr;
  AVPacket* packet_ = nullptr;
};

// MPEG audio: one packet per frame, sized from its header.
bool DecodeMpeg(const uint8_t* data, size_t size, const Sample& sample, std::vector<int16_t>& out) {
  Decoder decoder(AV_CODEC_ID_MP3, sample.frequency, sample.channels);
  if (!decoder.ok()) return false;
  static const int kBitrates[2][16] = {
      {0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0},  // MPEG-1 L3
      {0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0}};    // MPEG-2/2.5 L3
  static const int kRates[4][3] = {{11025, 12000, 8000}, {0, 0, 0}, {22050, 24000, 16000},
                                   {44100, 48000, 32000}};
  size_t at = 0;
  while (at + 4 <= size) {
    const uint8_t* h = data + at;
    if (h[0] != 0xFF || (h[1] & 0xE0) != 0xE0) {
      ++at;  // Padding between frames.
      continue;
    }
    const int version = (h[1] >> 3) & 3;  // 3: MPEG-1, 2: MPEG-2, 0: MPEG-2.5.
    const int layer = (h[1] >> 1) & 3;    // 1: Layer III.
    const int bitrate_index = h[2] >> 4;
    const int rate_index = (h[2] >> 2) & 3;
    if (version == 1 || layer != 1 || rate_index == 3 || !kBitrates[version != 3][bitrate_index]) {
      ++at;
      continue;
    }
    const int bitrate = kBitrates[version != 3][bitrate_index] * 1000;
    const int rate = kRates[version][rate_index];
    const size_t length = size_t((version == 3 ? 144 : 72) * bitrate / rate + ((h[2] >> 1) & 1));
    if (at + length > size) break;
    decoder.Decode(h, length, out);
    at += length;
  }
  return true;
}

// XMA: the packets' payloads form one bitstream of frames, each led by its
// 15-bit length; a packet's header gives where its first frame starts.
bool DecodeXma(const uint8_t* data, size_t size, const Sample& sample, std::vector<int16_t>& out) {
  constexpr size_t kPacket = 2048, kPacketHeaderBits = 32, kPayloadBits = (kPacket - 4) * 8;
  const size_t packets = size / kPacket;
  if (!packets || sample.channels < 1 || sample.channels > 2) return false;
  std::vector<uint8_t> payload(packets * (kPacket - 4) + 16, 0);
  for (size_t i = 0; i < packets; ++i) {
    std::memcpy(&payload[i * (kPacket - 4)], data + i * kPacket + 4, kPacket - 4);
  }
  Decoder decoder(AV_CODEC_ID_XMAFRAMES, sample.frequency, sample.channels);
  if (!decoder.ok()) return false;
  const size_t total_bits = packets * kPayloadBits;
  rex::stream::BitStream bits(payload.data(), total_bits);
  auto packet_first_frame = [&](size_t packet) -> std::optional<size_t> {
    const uint8_t* p = data + packet * kPacket;
    const uint32_t offset =
        uint32_t(((p[0] & 0x3) << 13) | (p[1] << 5) | (p[2] >> 3)) + kPacketHeaderBits;
    if (offset >= kPacket * 8) return std::nullopt;  // No frame starts here.
    return packet * kPayloadBits + (offset - kPacketHeaderBits);
  };
  std::optional<size_t> start = packet_first_frame(0);
  size_t bit = start.value_or(total_bits);
  std::vector<uint8_t> frame(4096 + 2, 0);
  std::vector<int16_t> decoded;
  while (bit + 15 <= total_bits) {
    bits.SetOffset(bit);
    const uint32_t length = uint32_t(bits.Peek(15));
    if (length == 0x7FFF || length < 15 || bit + length > total_bits) {
      // The packet's padding: continue at the next packet's first frame.
      size_t packet = bit / kPayloadBits + 1;
      std::optional<size_t> next;
      while (packet < packets && !(next = packet_first_frame(packet))) ++packet;
      if (!next || *next <= bit) break;
      bit = *next;
      continue;
    }
    std::fill(frame.begin(), frame.end(), 0);
    const uint32_t padding = uint32_t(bits.Copy(frame.data() + 1, length));
    const size_t bytes = 1 + (padding + length + 7) / 8;
    const uint32_t padding_end = uint32_t(bytes * 8 - (8 + padding + length));
    frame[0] = uint8_t(((padding & 7) << 5) | ((padding_end & 7) << 2));
    decoder.Decode(frame.data(), bytes, decoded);
    bit += length;
  }
  // The decoder's output trails the bitstream by its start padding.
  const size_t skip = size_t(192) * sample.channels;
  if (decoded.size() > skip) out.insert(out.end(), decoded.begin() + skip, decoded.end());
  return true;
}

bool WriteWav(const std::filesystem::path& path, const std::vector<int16_t>& pcm, int rate,
              int channels) {
  std::ofstream file(path, std::ios::binary);
  auto u32 = [&](uint32_t v) { file.write(reinterpret_cast<const char*>(&v), 4); };
  auto u16 = [&](uint16_t v) { file.write(reinterpret_cast<const char*>(&v), 2); };
  const uint32_t bytes = uint32_t(pcm.size() * 2);
  file.write("RIFF", 4);
  u32(36 + bytes);
  file.write("WAVEfmt ", 8);
  u32(16);
  u16(1);
  u16(uint16_t(channels));
  u32(uint32_t(rate));
  u32(uint32_t(rate * channels * 2));
  u16(uint16_t(channels * 2));
  u16(16);
  file.write("data", 4);
  u32(bytes);
  file.write(reinterpret_cast<const char*>(pcm.data()), bytes);
  return bool(file);
}

std::string JsonString(const std::string& text) {
  std::string out = "\"";
  for (unsigned char c : text) {
    if (c == '"' || c == '\\') out += '\\', out += char(c);
    else if (c < 0x20) {
      char buffer[8];
      std::snprintf(buffer, sizeof(buffer), "\\u%04x", c);
      out += buffer;
    } else out += char(c);
  }
  return out + "\"";
}

const char* Codec(uint32_t mode) {
  if (mode & kModeXma) return "xma";
  if (mode & kModeMpeg) return "mpeg";
  if (mode & kModePcm16) return "pcm16";
  return "unknown";
}

// A file name from the sample's name: letters, digits, '-' and '_'.
std::string SafeName(const Sample& sample) {
  std::string name;
  for (char c : sample.name) {
    name += (std::isalnum(static_cast<unsigned char>(c)) || c == '-' || c == '_') ? c : '_';
  }
  char prefix[16];
  std::snprintf(prefix, sizeof(prefix), "%04u", sample.index);
  return name.empty() ? prefix : std::string(prefix) + "_" + name;
}

}  // namespace

int main(int argc, char** argv) {
  const bool list = argc == 3 && std::string(argv[1]) == "--list";
  if (!list && argc != 3 && !(argc == 5 && std::string(argv[3]) == "--sample")) {
    std::cerr << "usage: pinyon_shift_fh1_audio_decode <bank.fsb> <output folder> [--sample N]\n"
                 "       pinyon_shift_fh1_audio_decode --list <bank.fsb>\n";
    return 2;
  }
  const std::filesystem::path bank_path = list ? argv[2] : argv[1];
  std::ifstream input(bank_path, std::ios::binary);
  std::vector<uint8_t> data((std::istreambuf_iterator<char>(input)), {});
  std::string error;
  const auto samples = ReadBank(data, error);
  if (!samples) {
    std::cerr << bank_path.string() << ": " << error << "\n";
    return 1;
  }
  const std::filesystem::path output = list ? std::filesystem::path() : argv[2];
  const long only = argc == 5 ? std::strtol(argv[4], nullptr, 10) : -1;
  int failures = 0;
  for (const Sample& sample : *samples) {
    if (only >= 0 && long(sample.index) != only) continue;
    std::string line = "{\"index\":" + std::to_string(sample.index) +
                       ",\"name\":" + JsonString(sample.name) + ",\"codec\":\"" +
                       Codec(sample.mode) + "\",\"channels\":" + std::to_string(sample.channels) +
                       ",\"rate\":" + std::to_string(sample.frequency) +
                       ",\"length_samples\":" + std::to_string(sample.length_samples);
    if (!list) {
      std::vector<int16_t> pcm;
      const uint8_t* bytes = data.data() + sample.offset;
      bool decoded = false;
      if (sample.mode & kModeXma) {
        decoded = DecodeXma(bytes, sample.length_bytes, sample, pcm);
      } else if (sample.mode & kModeMpeg) {
        decoded = DecodeMpeg(bytes, sample.length_bytes, sample, pcm);
      } else if (sample.mode & kModePcm16) {
        pcm.resize(sample.length_bytes / 2);
        for (size_t i = 0; i < pcm.size(); ++i) {
          const uint8_t* p = bytes + i * 2;
          pcm[i] = int16_t((sample.mode & kModeBigEndian) ? (p[0] << 8 | p[1]) : (p[1] << 8 | p[0]));
        }
        decoded = true;
      }
      // Keep the declared length: decoders pad their last frame.
      const size_t declared = size_t(sample.length_samples) * sample.channels;
      if (decoded && declared && pcm.size() > declared) pcm.resize(declared);
      const auto file = output / (SafeName(sample) + ".wav");
      if (decoded && !pcm.empty() &&
          WriteWav(file, pcm, sample.frequency, std::max<int>(1, sample.channels))) {
        line += ",\"file\":" + JsonString(file.filename().string()) +
                ",\"decoded_samples\":" + std::to_string(pcm.size() / std::max<int>(1, sample.channels));
      } else {
        line += ",\"error\":\"not decoded\"";
        ++failures;
      }
    }
    std::cout << line << "}\n";
  }
  return failures ? 3 : 0;
}
