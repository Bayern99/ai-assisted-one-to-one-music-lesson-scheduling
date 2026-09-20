import Darwin
import Foundation

enum LoopbackPortError: LocalizedError {
    case socketCreation(Int32)
    case bind(Int32)
    case inspect(Int32)

    var errorDescription: String? {
        switch self {
        case let .socketCreation(code):
            return "Could not create a loopback socket (errno \(code))."
        case let .bind(code):
            return "Could not reserve a loopback port (errno \(code))."
        case let .inspect(code):
            return "Could not inspect the reserved loopback port (errno \(code))."
        }
    }
}

enum LoopbackPort {
    static func available() throws -> UInt16 {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw LoopbackPortError.socketCreation(errno) }
        defer { close(descriptor) }

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        let bindResult = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bindResult == 0 else { throw LoopbackPortError.bind(errno) }

        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let inspectResult = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                getsockname(descriptor, $0, &length)
            }
        }
        guard inspectResult == 0 else { throw LoopbackPortError.inspect(errno) }
        return UInt16(bigEndian: address.sin_port)
    }
}
