using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Controls;

public sealed partial class StatusCard : UserControl
{
    public StatusCard() => InitializeComponent();

    public string Title
    {
        get => TitleText.Text;
        set => TitleText.Text = value;
    }

    public string Detail
    {
        get => DetailText.Text;
        set => DetailText.Text = value;
    }

    public string Glyph
    {
        get => StateIcon.Glyph;
        set => StateIcon.Glyph = value;
    }

    public UIElement? ActionContent
    {
        get => ActionPresenter.Content as UIElement;
        set => ActionPresenter.Content = value;
    }
}
