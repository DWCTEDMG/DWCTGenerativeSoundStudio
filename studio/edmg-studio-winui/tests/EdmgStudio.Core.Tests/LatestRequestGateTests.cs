using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class LatestRequestGateTests
{
  [TestMethod]
  public void SupersededResponseCannotPublishEvenWhenTransportCompletes()
  {
    LatestRequestGate gate = new();
    using LatestRequestGate.Request first = gate.Begin();
    using LatestRequestGate.Request second = gate.Begin();
    Assert.IsTrue(first.Token.IsCancellationRequested);
    Assert.IsFalse(first.IsCurrent);
    Assert.IsTrue(second.IsCurrent);
    first.Dispose();
    Assert.IsTrue(second.IsCurrent);
  }

  [TestMethod]
  public void NavigatingAwayInvalidatesPendingReadAndAllowsFreshVisit()
  {
    LatestRequestGate gate = new();
    using LatestRequestGate.Request first = gate.Begin();
    gate.Cancel();
    Assert.IsFalse(first.IsCurrent);
    Assert.IsTrue(first.Token.IsCancellationRequested);
    using LatestRequestGate.Request nextVisit = gate.Begin();
    Assert.IsTrue(nextVisit.IsCurrent);
  }

  [TestMethod]
  public void CallerCancellationPreventsPublication()
  {
    LatestRequestGate gate = new();
    using CancellationTokenSource cancellation = new();
    using LatestRequestGate.Request request = gate.Begin(cancellation.Token);
    cancellation.Cancel();
    Assert.IsFalse(request.IsCurrent);
    Assert.IsTrue(request.Token.IsCancellationRequested);
  }
}
