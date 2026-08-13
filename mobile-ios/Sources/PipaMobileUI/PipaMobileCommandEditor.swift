import PipaMobileCore
import SwiftUI

@available(iOS 16.0, macOS 13.0, *)
public extension PipaMobileCommand {
    /// Placeholders are presentation data from the non-sensitive catalog.
    /// They are never sent to the agent until the user completes the draft.
    var placeholders: [String] {
        var labels: [String] = []
        var cursor = phrase.startIndex
        while let open = phrase[cursor...].firstIndex(of: "<") {
            let afterOpen = phrase.index(after: open)
            guard let close = phrase[afterOpen...].firstIndex(of: ">") else { break }
            let label = String(phrase[afterOpen..<close])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !label.isEmpty, label.utf8.count <= 80, !labels.contains(label) {
                labels.append(label)
            }
            cursor = phrase.index(after: close)
        }
        return labels
    }

    /// Render a completed catalog phrase without executing it.
    ///
    /// The same 4,000-byte bound used by `sendText` is applied here. Control
    /// characters are rejected so a pasted value cannot alter the line-based
    /// protocol or make the preview misleading.
    func rendered(with values: [String: String]) -> String? {
        var rendered = phrase
        for (index, label) in placeholders.enumerated() {
            guard let rawValue = values[label] else { return nil }
            let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
            let parameter = parameters.count == placeholders.count ? parameters[index] : nil
            let safe = parameter?.kind == "message"
                ? PipaMobileTextPolicy.isSafeMessageText(value, maxBytes: parameter?.maxLength ?? 4096)
                : PipaMobileTextPolicy.isSafeDisplayText(value, maxBytes: parameter?.maxLength ?? 4096)
            guard safe else {
                return nil
            }
            rendered = rendered.replacingOccurrences(of: "<\(label)>", with: value)
        }
        let renderedIsSafe = parameters.contains(where: { $0.kind == "message" })
            ? PipaMobileTextPolicy.isSafeMessageText(rendered, maxBytes: 4000)
            : PipaMobileTextPolicy.isSafeDisplayText(rendered, maxBytes: 4000)
        guard renderedIsSafe else { return nil }
        return rendered
    }

    /// Convert the visible form into the registered tool's typed arguments.
    /// Commands from older agents without parameter metadata keep using text.
    func toolArguments(with values: [String: String]) -> [String: Any]? {
        guard supportsStructuredArguments, parameters.count == placeholders.count else { return nil }
        if parameters.isEmpty {
            return values.isEmpty ? [:] : nil
        }
        var arguments: [String: Any] = [:]
        for (index, parameter) in parameters.enumerated() {
            let placeholder = placeholders[index]
            guard let rawValue = values[placeholder] else { return nil }
            let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
            let safe = parameter.kind == "message"
                ? PipaMobileTextPolicy.isSafeMessageText(value, maxBytes: parameter.maxLength)
                : PipaMobileTextPolicy.isSafeDisplayText(value, maxBytes: parameter.maxLength)
            guard safe,
                  Self.isValidStructuredValue(value, for: parameter),
                  parameter.options.isEmpty || parameter.options.contains(value) else {
                return nil
            }

            switch parameter.kind {
            case "integer":
                guard let integer = Int(value) else { return nil }
                arguments[parameter.id] = integer
            default:
                arguments[parameter.id] = value
            }
        }
        return arguments
    }

    private static func isValidStructuredValue(
        _ value: String,
        for parameter: PipaMobileCommandParameter
    ) -> Bool {
        switch parameter.kind {
        case "phone":
            let allowed = CharacterSet(charactersIn: "0123456789+ ().-")
            guard value.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return false }
            let compact = value.filter { !" ().-".contains($0) }
            let digits = compact.first == "+" ? String(compact.dropFirst()) : compact
            return (7...15).contains(digits.utf8.count) &&
                digits.utf8.allSatisfy { (0x30...0x39).contains($0) }
        case "channel_id", "guild_id":
            return (17...20).contains(value.utf8.count) &&
                value.utf8.allSatisfy { (0x30...0x39).contains($0) }
        default:
            return true
        }
    }
}

@available(iOS 16.0, macOS 13.0, *)
public struct PipaMobileCommandEditor: View {
    @Environment(\.dismiss) private var dismiss

    private let command: PipaMobileCommand
    private let onPrepare: (String) -> Void
    private let onExecute: ((PipaMobileCommand, [String: String]) -> Void)?
    @State private var values: [String: String]

    public init(
        command: PipaMobileCommand,
        onPrepare: @escaping (String) -> Void,
        onExecute: ((PipaMobileCommand, [String: String]) -> Void)? = nil
    ) {
        self.command = command
        self.onPrepare = onPrepare
        self.onExecute = onExecute
        _values = State(
            initialValue: Dictionary(uniqueKeysWithValues: command.placeholders.map { ($0, "") })
        )
    }

    public var body: some View {
        NavigationStack {
            Form {
                Section("Completa el comando") {
                    Text(command.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    ForEach(Array(command.placeholders.enumerated()), id: \.offset) { index, label in
                        field(
                            for: label,
                            parameter: command.parameters.count == command.placeholders.count
                                ? command.parameters[index]
                                : nil
                        )
                    }
                }

                Section("Vista previa") {
                    if let rendered = command.rendered(with: values) {
                        Text(rendered)
                            .font(.body.monospaced())
                            .textSelection(.enabled)
                    } else {
                        Text("Completa los campos para preparar el comando.")
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button("Preparar en el editor") {
                        guard let rendered = command.rendered(with: values) else { return }
                        onPrepare(rendered)
                        dismiss()
                    }
                    .disabled(command.rendered(with: values) == nil)

                    if onExecute != nil {
                        Button("Enviar acción estructurada") {
                            guard command.toolArguments(with: values) != nil else { return }
                            onExecute?(command, values)
                            dismiss()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(command.toolArguments(with: values) == nil)
                        Text("Usa los campos validados del comando y conserva la confirmación cuando sea necesaria.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle(command.id)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancelar") { dismiss() }
                }
            }
        }
    }

    @ViewBuilder
    private func field(for label: String, parameter: PipaMobileCommandParameter?) -> some View {
        let binding = Binding<String>(
            get: { values[label] ?? "" },
            set: { values[label] = $0 }
        )
        if parameter?.kind == "message" || label.localizedCaseInsensitiveContains("mensaje") {
            TextEditor(text: binding)
                .frame(minHeight: 90)
                .overlay(alignment: .topLeading) {
                    if binding.wrappedValue.isEmpty {
                        Text(label)
                            .foregroundStyle(.secondary)
                            .padding(.top, 8)
                            .allowsHitTesting(false)
                    }
                }
        } else if let options = parameter?.options, !options.isEmpty {
            Picker(label, selection: binding) {
                Text("Selecciona una opción").tag("")
                ForEach(options, id: \.self) { option in
                    Text(option).tag(option)
                }
            }
        } else {
            TextField(label, text: binding)
#if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(parameter?.kind == "phone" || label.localizedCaseInsensitiveContains("teléfono") ? .phonePad : .default)
#endif
        }
    }
}
