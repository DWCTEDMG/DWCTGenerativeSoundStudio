using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class CommandUndoContractsTests
{
    [TestMethod]
    public void EditTransaction_GroupsOperationsAndBuildsOperationalRequest()
    {
        JsonObject source = JsonNode.Parse("""{"schema_version":"1.0","project_id":"p1","operation_id":"op-1","expected_revision":7,"action":"edit","label":"Arrange clips","operations":[{"kind":"move","track_id":"video","clip_id":"clip-1","position":"9007199254740993"},{"kind":"set_mute","track_id":"video","clip_id":"clip-2","value":true}],"future":"keep"}""")!.AsObject();

        SharedCommandTransaction command = CommandUndoContracts.Parse(source);
        JsonObject request = CommandUndoContracts.BuildOperationalRequest(command);

        Assert.AreEqual(SharedCommandAction.Edit, command.Action);
        Assert.HasCount(2, command.Operations);
        Assert.AreEqual("9007199254740993", command.Operations[0]["position"]!.GetValue<string>());
        Assert.AreEqual("edit", request["action"]!.GetValue<string>());
        Assert.HasCount(2, request["operations"]!.AsArray());
        Assert.AreEqual("keep", command.Metadata["future"]!.GetValue<string>());
        Assert.AreEqual("keep", request["future"]!.GetValue<string>());
        Assert.IsNull(request["schema_version"]);
        Assert.IsNull(request["project_id"]);
    }

    [TestMethod]
    public void CommandPayload_EnforcesTransactionActionShape()
    {
        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.Parse(JsonNode.Parse("""{"project_id":"p","operation_id":"op","expected_revision":1,"action":"edit","operations":[]}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.Parse(JsonNode.Parse("""{"project_id":"p","operation_id":"op","expected_revision":1,"action":"replace"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.Parse(JsonNode.Parse("""{"project_id":"p","operation_id":"op","expected_revision":1,"action":"undo","timeline":{}}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.Parse(JsonNode.Parse("""{"project_id":"p","operation_id":"op","expected_revision":1,"action":"edit","operations":[{"track_id":"video"}]}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.Parse(JsonNode.Parse("""{"id":"different","project_id":"p","operation_id":"op","expected_revision":1,"action":"undo"}""")!.AsObject()));
    }

    [TestMethod]
    public void HistoryState_RejectsUnsafeExternalHistory()
    {
        SharedCommandHistoryState state = CommandUndoContracts.ParseHistory(JsonNode.Parse("""{"can_undo":true,"can_redo":false,"undo_label":"Move clip","redo_label":null,"external_change":false}""")!.AsObject());
        Assert.IsTrue(state.CanUndo);
        Assert.AreEqual("Move clip", state.UndoLabel);

        Assert.Throws<InvalidDataException>(() => CommandUndoContracts.ParseHistory(JsonNode.Parse("""{"can_undo":true,"can_redo":false,"undo_label":"Move","redo_label":null,"external_change":true}""")!.AsObject()));
    }
}
