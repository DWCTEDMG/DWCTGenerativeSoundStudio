using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public enum SharedCommandAction
{
    Edit,
    Replace,
    Undo,
    Redo,
}

public sealed record SharedCommandTransaction(
    string SchemaVersion,
    string ProjectId,
    string OperationId,
    long ExpectedRevision,
    SharedCommandAction Action,
    string Label,
    IReadOnlyList<JsonObject> Operations,
    JsonObject? Timeline,
    string? Source,
    JsonObject Metadata);

public sealed record SharedCommandHistoryState(
    bool CanUndo,
    bool CanRedo,
    string? UndoLabel,
    string? RedoLabel,
    bool ExternalChange);

public static class CommandUndoContracts
{
    public const string SchemaVersion = "1.0";

    public static SharedCommandTransaction Parse(JsonElement command) =>
        Parse(JsonNode.Parse(command.GetRawText())?.AsObject() ?? throw new InvalidDataException("Command must be an object."));

    public static SharedCommandTransaction Parse(JsonObject command)
    {
        string schemaVersion = OptionalString(command, "schema_version") ?? SchemaVersion;
        if (schemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported command schema version '{schemaVersion}'.");
        string projectId = RequiredString(command, "project_id");
        string operationId = RequiredString(command, "operation_id");
        ValidateIdentity(projectId, operationId);
        string? contractId = OptionalString(command, "id");
        if (contractId is not null && contractId != operationId) throw new InvalidDataException("Command ID must match its idempotent operation ID.");
        long expectedRevision = RequiredInt64(command, "expected_revision");
        if (expectedRevision < 1) throw new InvalidDataException("Expected revision must be positive.");
        SharedCommandAction action = RequiredString(command, "action") switch
        {
            "edit" => SharedCommandAction.Edit,
            "replace" => SharedCommandAction.Replace,
            "undo" => SharedCommandAction.Undo,
            "redo" => SharedCommandAction.Redo,
            string value => throw new InvalidDataException($"Unsupported command action '{value}'."),
        };
        string label = OptionalString(command, "label") ?? "Timeline edit";
        if (string.IsNullOrWhiteSpace(label) || label.Length > 200) throw new InvalidDataException("Command label must contain 1 to 200 characters.");
        IReadOnlyList<JsonObject> operations = ReadOperations(command["operations"]);
        JsonObject? timeline = command["timeline"] switch
        {
            null => null,
            JsonObject value => value.DeepClone().AsObject(),
            _ => throw new InvalidDataException("Replacement timeline must be an object."),
        };
        ValidatePayload(action, operations, timeline);
        return new SharedCommandTransaction(schemaVersion, projectId, operationId, expectedRevision, action,
            label, operations, timeline, OptionalString(command, "source"), command.DeepClone().AsObject());
    }

    public static JsonObject BuildOperationalRequest(SharedCommandTransaction command)
    {
        ArgumentNullException.ThrowIfNull(command);
        if (command.SchemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported command schema version '{command.SchemaVersion}'.");
        ValidateIdentity(command.ProjectId, command.OperationId);
        if (command.ExpectedRevision < 1) throw new InvalidDataException("Expected revision must be positive.");
        if (string.IsNullOrWhiteSpace(command.Label) || command.Label.Length > 200) throw new InvalidDataException("Command label must contain 1 to 200 characters.");
        if (command.Source?.Length > 160) throw new InvalidDataException("Command source cannot exceed 160 characters.");
        ValidatePayload(command.Action, command.Operations, command.Timeline);
        JsonObject result = command.Metadata.DeepClone().AsObject();
        foreach (string contractField in new[] { "schema_version", "contract_type", "id", "project_id", "created_at", "updated_at", "source", "metadata" })
        {
            result.Remove(contractField);
        }
        result["operation_id"] = command.OperationId;
        result["expected_revision"] = command.ExpectedRevision;
        result["action"] = ActionName(command.Action);
        result["label"] = command.Label;
        result["operations"] = new JsonArray(command.Operations.Select(operation => (JsonNode?)operation.DeepClone()).ToArray());
        if (command.Timeline is not null) result["timeline"] = command.Timeline.DeepClone();
        else result.Remove("timeline");
        return result;
    }

    public static SharedCommandHistoryState ParseHistory(JsonElement history) =>
        ParseHistory(JsonNode.Parse(history.GetRawText())?.AsObject() ?? throw new InvalidDataException("Command history must be an object."));

    public static SharedCommandHistoryState ParseHistory(JsonObject history)
    {
        bool canUndo = RequiredBoolean(history, "can_undo");
        bool canRedo = RequiredBoolean(history, "can_redo");
        string? undoLabel = OptionalString(history, "undo_label");
        string? redoLabel = OptionalString(history, "redo_label");
        bool externalChange = RequiredBoolean(history, "external_change");
        if (!canUndo && undoLabel is not null) throw new InvalidDataException("Undo label requires an available undo command.");
        if (!canRedo && redoLabel is not null) throw new InvalidDataException("Redo label requires an available redo command.");
        if (externalChange && (canUndo || canRedo)) throw new InvalidDataException("Externally changed history cannot advertise undo or redo.");
        return new SharedCommandHistoryState(canUndo, canRedo, undoLabel, redoLabel, externalChange);
    }

    private static IReadOnlyList<JsonObject> ReadOperations(JsonNode? node)
    {
        if (node is null) return [];
        if (node is not JsonArray array || array.Count > 200) throw new InvalidDataException("Command operations must be an array of at most 200 entries.");
        return array.Select(item => item as JsonObject ?? throw new InvalidDataException("Command operations must be objects."))
            .Select(item => item.DeepClone().AsObject()).ToArray();
    }

    private static void ValidatePayload(SharedCommandAction action, IReadOnlyList<JsonObject> operations, JsonObject? timeline)
    {
        if (action == SharedCommandAction.Edit)
        {
            if (operations.Count == 0 || timeline is not null) throw new InvalidDataException("Edit commands require operations and cannot replace the timeline.");
            foreach (JsonObject operation in operations) _ = RequiredString(operation, "kind");
        }
        else if (action == SharedCommandAction.Replace)
        {
            if (timeline is null || operations.Count != 0) throw new InvalidDataException("Replace commands require only a replacement timeline.");
        }
        else if (operations.Count != 0 || timeline is not null)
        {
            throw new InvalidDataException("Undo and redo commands cannot include mutation payloads.");
        }
    }

    private static string ActionName(SharedCommandAction action) => action switch
    {
        SharedCommandAction.Edit => "edit",
        SharedCommandAction.Replace => "replace",
        SharedCommandAction.Undo => "undo",
        SharedCommandAction.Redo => "redo",
        _ => throw new ArgumentOutOfRangeException(nameof(action)),
    };
    private static void ValidateIdentity(string projectId, string operationId)
    {
        if (string.IsNullOrWhiteSpace(projectId) || projectId.Length > 160) throw new InvalidDataException("Project ID must contain 1 to 160 characters.");
        if (string.IsNullOrWhiteSpace(operationId) || operationId.Length > 128) throw new InvalidDataException("Operation ID must contain 1 to 128 characters.");
    }
    private static string RequiredString(JsonObject source, string name) =>
        OptionalString(source, name) is string value && !string.IsNullOrWhiteSpace(value) ? value : throw new InvalidDataException($"'{name}' is required.");
    private static string? OptionalString(JsonObject source, string name) => source[name] is null ? null
        : source[name] is JsonValue value && value.TryGetValue<string>(out string? result) ? result
        : throw new InvalidDataException($"'{name}' must be a string.");
    private static long RequiredInt64(JsonObject source, string name) =>
        source[name] is JsonValue value && value.TryGetValue<long>(out long result) ? result : throw new InvalidDataException($"'{name}' must be an integer.");
    private static bool RequiredBoolean(JsonObject source, string name) =>
        source[name] is JsonValue value && value.TryGetValue<bool>(out bool result) ? result : throw new InvalidDataException($"'{name}' must be a Boolean.");
}
