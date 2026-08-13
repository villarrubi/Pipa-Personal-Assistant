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
        for label in placeholders {
            guard let rawValue = values[label] else { return nil }
            let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard PipaMobileTextPolicy.isSafeDisplayText(value, maxBytes: 4096) else {
                return nil
            }
            rendered = rendered.replacingOccurrences(of: "<\(label)>", with: value)
        }
        guard PipaMobileTextPolicy.isSafeDisplayText(rendered, maxBytes: 4000) else { return nil }
        return rendered
    }
}

@available(iOS 16.0, macOS 13.0, *)
public struct PipaMobileCommandEditor: View {
    @Environment(\.dismiss) private var dismiss

    private let command: PipaMobileCommand
    private let onPrepare: (String) -> Void
    @State private var values: [String: String]

    public init(command: PipaMobileCommand, onPrepare: @escaping (String) -> Void) {
        self.command = command
        self.onPrepare = onPrepare
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
                    ForEach(command.placeholders, id: \.self) { label in
                        field(for: label)
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
    private func field(for label: String) -> some View {
        let binding = Binding<String>(
            get: { values[label] ?? "" },
            set: { values[label] = $0 }
        )
        if label.localizedCaseInsensitiveContains("mensaje") {
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
        } else {
            TextField(label, text: binding)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
#if os(iOS)
                .keyboardType(label.localizedCaseInsensitiveContains("teléfono") ? .phonePad : .default)
#endif
        }
    }
}
