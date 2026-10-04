using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.WinUI.Pages;

internal static class StudioPageHelpers
{
  public static string UserMessage(Exception exception)
  {
    return exception is StudioApiException api
      ? api.Hint is { Length: > 0 }
          ? $"{api.Message} {api.Hint}"
          : api.Message
      : exception.Message;
  }

  public static string PrettyJson(JsonElement value)
  {
    if (value.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
    {
      return string.Empty;
    }

    using MemoryStream stream = new();
    using (Utf8JsonWriter writer = new(stream, new JsonWriterOptions { Indented = true }))
    {
      value.WriteTo(writer);
    }

    return Encoding.UTF8.GetString(stream.GetBuffer(), 0, checked((int)stream.Length));
  }

  public static JsonObject ToObject(JsonElement value)
  {
    return JsonNode.Parse(value.GetRawText())?.AsObject()
             ?? throw new JsonException("Studio returned an invalid JSON object.");
  }

  public static string GetErrorMessage(Exception exception)
  {
    return UserMessage(exception);
  }

  public static string GetUserFacingError(Exception exception)
  {
    return UserMessage(exception);
  }

  public static long? ExpectedRevision(ProjectDto? project)
  {
    return project is { Revision: > 0 } ? project.Revision : null;
  }

  public static async Task<bool> ConfirmReloadAfterRevisionConflictAsync(
        XamlRoot xamlRoot,
        ProjectRevisionConflictException conflict)
  {
    string revisionDetail = conflict.ExpectedRevision is long expected &&
                            conflict.ActualRevision is long actual
        ? $" This window had revision {expected}; the project is now revision {actual}."
        : string.Empty;
    ContentDialog dialog = new()
    {
      XamlRoot = xamlRoot,
      Title = "Project changed elsewhere",
      Content =
                $"Your change was not applied because another operation updated this project.{revisionDetail} " +
                "Reload the latest project, review your local changes, then retry. Studio will not retry the change automatically.",
      PrimaryButtonText = "Reload project",
      CloseButtonText = "Review local changes",
      DefaultButton = ContentDialogButton.Close,
    };

    return await dialog.ShowAsync() == ContentDialogResult.Primary;
  }

  public static string FormatJson(JsonNode? value)
  {
    if (value is null)
    {
      return string.Empty;
    }

    using MemoryStream stream = new();
    using (Utf8JsonWriter writer = new(stream, new JsonWriterOptions { Indented = true }))
    {
      value.WriteTo(writer);
    }

    return Encoding.UTF8.GetString(stream.GetBuffer(), 0, checked((int)stream.Length));
  }

  public static string FormatJson(JsonElement value)
  {
    return PrettyJson(value);
  }

  public static JsonElement ToElement(JsonNode value)
  {
    using MemoryStream stream = new();
    using (Utf8JsonWriter writer = new(stream))
    {
      value.WriteTo(writer);
    }

    using JsonDocument document = JsonDocument.Parse(
        stream.GetBuffer().AsMemory(0, checked((int)stream.Length)));
    return document.RootElement.Clone();
  }

  public static string ShortId(string? value)
  {
    return string.IsNullOrWhiteSpace(value) || value.Length <= 12 ? value ?? string.Empty : value[..12];
  }

  public static void SetControlsEnabled(DependencyObject root, bool enabled)
  {
    for (int index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
    {
      DependencyObject child = VisualTreeHelper.GetChild(root, index);
      if (child is Control control)
      {
        control.IsEnabled = enabled;
      }
      else
      {
        SetControlsEnabled(child, enabled);
      }
    }
  }

  public static Task<bool> ConfirmAsync(
      XamlRoot xamlRoot,
      StudioActionConfirmation confirmation)
  {
    return ConfirmAsync(
              xamlRoot,
              confirmation.Title,
              confirmation.Message,
              confirmation.PrimaryButtonText);
  }

  public static async Task<bool> ConfirmAsync(
        XamlRoot xamlRoot,
        string title,
        string message,
        string primaryButtonText)
  {
    ContentDialog confirmation = new()
    {
      XamlRoot = xamlRoot,
      Title = title,
      Content = message,
      PrimaryButtonText = primaryButtonText,
      CloseButtonText = "Cancel",
      DefaultButton = ContentDialogButton.Close,
    };

    return await confirmation.ShowAsync() == ContentDialogResult.Primary;
  }
}
