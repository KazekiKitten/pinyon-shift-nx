using System.Text;
using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using Avalonia.Threading;

namespace PinyonShift.Launcher.Desktop;

public partial class MainWindow : Window
{
    private const string Repository = "https://github.com/arcanite24/pinyon-shift";
    private enum Mode { Loading, Setup, Building, Ready, Playing }

    private Installation? _installation;
    private string? _discImage;
    private Mode _mode = Mode.Loading;
    private CancellationTokenSource? _cancel;
    private readonly StringBuilder _log = new();

    public MainWindow()
    {
        InitializeComponent();
        VersionText.Text = $"Pinyon Shift {Installation.Version} · Not affiliated with Microsoft or Playground Games";
        AddHandler(DragDrop.DropEvent, OnDrop);
        AddHandler(DragDrop.DragOverEvent, (_, e) =>
            e.DragEffects = _mode == Mode.Setup ? DragDropEffects.Copy : DragDropEffects.None);
        Opened += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            _installation = await Installation.OpenAsync();
        }
        catch (Exception error)
        {
            Headline.Text = "Something is missing";
            Subhead.Text = error.Message;
            SetupPanel.IsVisible = false;
            PrimaryButton.IsVisible = false;
            return;
        }
        _ = StartUpdateCheckAsync();
        InstallText.Text = $"Installs to {_installation.Root}. The build needs about "
            + (Installation.IsMac ? "20" : "45") + " GB free and takes 20 to 60 minutes.";
        if (!Installation.HasAppleDeveloperTools())
        {
            AppleToolsPanel.IsVisible = true;
            SetupPanel.IsVisible = false;
            PrimaryButton.IsVisible = false;
            Headline.Text = "Build your copy";
            return;
        }
        ShowMode(_installation.IsReady() ? Mode.Ready : Mode.Setup);
    }

    private void ShowMode(Mode mode)
    {
        _mode = mode;
        var ready = mode is Mode.Ready or Mode.Playing;
        SetupPanel.IsVisible = mode == Mode.Setup;
        AppleToolsPanel.IsVisible = false;
        PrimaryButton.IsVisible = true;
        SteamButton.IsVisible = ready && Installation.IsLinux;
        RebuildButton.IsVisible = mode == Mode.Ready;
        XePanel.IsVisible = mode == Mode.Ready;
        XeControls.IsEnabled = mode == Mode.Ready;
        if (mode == Mode.Ready) _ = RefreshXeAsync();
        RadioPanel.IsVisible = mode == Mode.Ready;
        RadioControls.IsEnabled = mode == Mode.Ready;
        RadioList.IsEnabled = mode == Mode.Ready;
        if (mode == Mode.Ready) _ = ChangeRadioAsync(Array.Empty<string>(), "Reading stations…", null);
        CancelButton.IsVisible = mode == Mode.Building;
        if (mode == Mode.Building) ProgressPanel.IsVisible = true;
        switch (mode)
        {
            case Mode.Setup:
                Headline.Text = "Build your copy";
                Subhead.Text = "Verified, extracted and compiled on this computer. Nothing is uploaded.";
                PrimaryButton.Content = "Verify and build";
                UpdatePrimary();
                break;
            case Mode.Building:
                Headline.Text = "Building";
                Subhead.Text = "Your computer stays awake until the build is done. Closing this window stops it.";
                PrimaryButton.Content = "Building…";
                PrimaryButton.IsEnabled = false;
                break;
            case Mode.Ready:
                Headline.Text = "Ready to drive";
                Subhead.Text = "Vulkan · F6 or the pause menu opens settings in game.";
                PrimaryButton.Content = "▶  Play";
                PrimaryButton.IsEnabled = true;
                ProgressPanel.IsVisible = false;
                break;
            case Mode.Playing:
                Headline.Text = "Driving";
                Subhead.Text = "The game is running.";
                PrimaryButton.Content = "Running…";
                PrimaryButton.IsEnabled = false;
                break;
        }
    }

    private void UpdatePrimary() =>
        PrimaryButton.IsEnabled = _mode == Mode.Setup && _discImage is not null && OwnershipCheck.IsChecked == true;

    private void SetDisc(string path)
    {
        _discImage = path;
        DiscText.Text = Path.GetFileName(path);
        UpdatePrimary();
    }

    private async void Browse_Click(object? sender, RoutedEventArgs e)
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Choose your Forza Horizon disc image",
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("Disc image") { Patterns = new[] { "*.iso", "*.ISO" } },
                FilePickerFileTypes.All,
            },
        });
        var path = files.Count > 0 ? files[0].TryGetLocalPath() : null;
        if (path is not null) SetDisc(path);
    }

    private void OnDrop(object? sender, DragEventArgs e)
    {
        if (_mode != Mode.Setup) return;
        var path = e.DataTransfer.TryGetFiles()?.Select(item => item.TryGetLocalPath()).FirstOrDefault(p => p is not null);
        if (path is not null && File.Exists(path)) SetDisc(path);
    }

    private void Ownership_Changed(object? sender, RoutedEventArgs e) => UpdatePrimary();

    private async void Primary_Click(object? sender, RoutedEventArgs e)
    {
        if (_installation is null) return;
        if (_mode == Mode.Setup && _discImage is not null)
            await BuildAsync(new[] { "setup", "--json", "--iso", _discImage });
        else if (_mode == Mode.Ready)
            await PlayAsync();
    }

    private async void Rebuild_Click(object? sender, RoutedEventArgs e) =>
        await BuildAsync(new[] { "setup", "--json", "--build-only" });

    private async Task BuildAsync(string[] arguments)
    {
        if (_installation is null) return;
        _log.Clear();
        LogBox.Text = "";
        StatusText.Text = "";
        Progress.Value = 0;
        ShowMode(Mode.Building);
        _cancel = new CancellationTokenSource();
        string? failure = null;
        var code = await _installation.RunAsync(arguments, update => Dispatcher.UIThread.Post(() =>
        {
            if (update.Error is not null)
            {
                failure = update.Error;
                return;
            }
            Progress.Value = OverallPercent(update.Stage, update.Percent);
            PercentText.Text = $"{Progress.Value:0}%";
            if (update.Message is not null) ProgressMessage.Text = update.Message;
        }), AppendLog, _cancel.Token);
        var cancelled = _cancel.IsCancellationRequested;
        _cancel = null;
        if (code == 0)
        {
            ShowMode(Mode.Ready);
            StatusText.Text = Installation.IsLinux
                ? "Built. Add it to Steam to play from Game Mode with a controller."
                : "Built.";
            return;
        }
        ShowMode(_installation.IsReady() ? Mode.Ready : Mode.Setup);
        ProgressPanel.IsVisible = true;
        StatusText.Foreground = (Avalonia.Media.IBrush)this.FindResource("RedBrush")!;
        StatusText.Text = cancelled ? "Stopped." : failure ?? $"The build stopped (exit {code}). See the details or the logs.";
    }

    // setup's stages, weighted by how long each one takes.
    private static double OverallPercent(string stage, double percent) => stage switch
    {
        "verify" => percent * 0.01,
        "extract" => 1 + percent * 0.09,
        "tools" => 10 + percent * 0.10,
        "build" => 20 + percent * 0.80,
        "play" => 100,
        _ => 0,
    };

    private void AppendLog(string line) => Dispatcher.UIThread.Post(() =>
    {
        _log.AppendLine(line);
        if (_log.Length > 200_000) _log.Remove(0, _log.Length - 150_000);
        if (LogBox.IsVisible)
        {
            LogBox.Text = _log.ToString();
            LogBox.CaretIndex = LogBox.Text.Length;
        }
    });

    private async Task PlayAsync()
    {
        if (_installation is null) return;
        ShowMode(Mode.Playing);
        StatusText.Text = "";
        var code = await _installation.RunAsync(new[] { "launch" }, _ => { }, AppendLog);
        ShowMode(Mode.Ready);
        if (code != 0)
            StatusText.Text = $"The game stopped unexpectedly (exit {code}). Logs has the details; "
                + "Report a problem opens an issue.";
    }

    private async void Steam_Click(object? sender, RoutedEventArgs e)
    {
        if (_installation is null) return;
        SteamButton.IsEnabled = false;
        StatusText.Text = "Adding to Steam (Steam restarts if it is open)…";
        var output = new StringBuilder();
        var code = await _installation.RunAsync(new[] { "shortcuts", "add" }, _ => { },
            line => { lock (output) output.AppendLine(line); });
        SteamButton.IsEnabled = true;
        StatusText.Text = code == 0
            ? "Added to Steam and the applications menu. On a Steam Deck, return to Game Mode and find "
              + "Pinyon Shift under Non-Steam in your library."
            : "Could not add it to Steam: " + output.ToString().Trim();
    }

    // The XE mod: tools/pinyon.py xe, which prints one JSON object with --json.
    private bool _xeInstalled, _xeEnabled;

    private async Task<JsonElement> RunXeAsync(params string[] arguments)
    {
        if (_installation is null) throw new InvalidOperationException("The installation is not ready.");
        var lines = new List<string>();
        var code = await _installation.RunAsync(new[] { "xe" }.Concat(arguments).Append("--json"), _ => { },
            line => { lock (lines) lines.Add(line); });
        string? json;
        lock (lines) json = lines.LastOrDefault(line => line.StartsWith('{'));
        if (json is null) throw new InvalidOperationException($"XE management stopped (exit {code}).");
        var result = JsonDocument.Parse(json).RootElement.Clone();
        if (code != 0 || result.TryGetProperty("error", out _))
            throw new InvalidOperationException(result.TryGetProperty("error", out var error)
                ? error.GetString() : $"XE management stopped (exit {code}).");
        return result;
    }

    private async Task RefreshXeAsync(string? message = null)
    {
        try
        {
            var status = await RunXeAsync("status");
            _xeInstalled = status.GetProperty("installed").GetBoolean();
            _xeEnabled = _xeInstalled && status.GetProperty("enabled").GetBoolean();
            var version = _xeInstalled ? status.GetProperty("version").GetString() : null;
            XeToggleButton.IsEnabled = _xeInstalled;
            XeToggleButton.Content = _xeEnabled ? "Turn off" : "Use XE";
            XeInstallButton.Content = _xeInstalled ? "Reinstall" : "Install XE";
            XeStatusText.Text = message ?? (!_xeInstalled
                ? "Not installed. Download from ModDB opens both downloads in your browser and installs them when they finish; Install XE takes archives you already have."
                : _xeEnabled
                    ? $"XE {version} is on. It plays its own new save and hides Horizon Rally; your save is kept."
                    : $"XE {version} is installed and off. The game runs as on the disc.");
        }
        catch (Exception error)
        {
            XeStatusText.Text = message ?? error.Message;
        }
    }

    private async Task ChangeXeAsync(string[] arguments, string working, string success)
    {
        XeControls.IsEnabled = false;
        PrimaryButton.IsEnabled = false;
        XeStatusText.Text = working;
        string message;
        try
        {
            await RunXeAsync(arguments);
            message = success;
        }
        catch (Exception error)
        {
            message = error.Message;
        }
        await RefreshXeAsync(message);
        XeControls.IsEnabled = true;
        PrimaryButton.IsEnabled = _mode == Mode.Ready;
    }

    private async void XeInstall_Click(object? sender, RoutedEventArgs e)
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Choose the XE 1.0 download and the 1.01 hotfix",
            AllowMultiple = true,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("XE mod archives") { Patterns = new[] { "*.7z" } },
                FilePickerFileTypes.All,
            },
        });
        var paths = files.Select(file => file.TryGetLocalPath()).OfType<string>().ToArray();
        if (paths.Length == 0) return;
        await ChangeXeAsync(new[] { "install" }.Concat(paths).Append("--replace").ToArray(),
            "Checking and extracting the XE archives. This takes a few minutes…",
            "XE is installed and on. Its first start creates a new save.");
    }

    // ModDB disallows automated downloads, so the player's browser fetches both
    // archives and the tool installs them from Downloads when they finish (#426).
    private async void XeDownload_Click(object? sender, RoutedEventArgs e)
    {
        await ChangeXeAsync(new[] { "install", "--find", "--open-pages", "--wait", "14400", "--replace" },
            "Download both files on the ModDB pages that opened (XE by Teancum, 3.7 GB). " +
            "Installing starts by itself when they finish in your Downloads folder…",
            "XE is installed and on. Its first start creates a new save.");
    }

    private async void XeToggle_Click(object? sender, RoutedEventArgs e)
    {
        if (!_xeInstalled) return;
        await ChangeXeAsync(new[] { _xeEnabled ? "disable" : "enable" }, "Updating…",
            _xeEnabled ? "XE is off. Your own save is used again." : "XE is on. It starts with a new save.");
    }

    // Custom radio stations: tools/pinyon.py radio, which prints one JSON
    // object with --json (#445).
    private async Task<JsonElement> RunRadioAsync(IEnumerable<string> arguments)
    {
        if (_installation is null) throw new InvalidOperationException("The installation is not ready.");
        var lines = new List<string>();
        var code = await _installation.RunAsync(new[] { "radio" }.Concat(arguments).Append("--json"), _ => { },
            line => { lock (lines) lines.Add(line); });
        string? json;
        lock (lines) json = lines.LastOrDefault(line => line.StartsWith('{'));
        if (json is null) throw new InvalidOperationException($"Radio management stopped (exit {code}).");
        var result = JsonDocument.Parse(json).RootElement.Clone();
        if (code != 0 || result.TryGetProperty("error", out _))
            throw new InvalidOperationException(result.TryGetProperty("error", out var error)
                ? error.GetString() : $"Radio management stopped (exit {code}).");
        return result;
    }

    // Runs one radio command (none: just list) and shows the stations.
    private async Task ChangeRadioAsync(string[] arguments, string working, string? success)
    {
        RadioControls.IsEnabled = false;
        RadioList.IsEnabled = false;
        RadioStatusText.Text = working;
        string? message = success;
        try
        {
            if (arguments.Length > 0) await RunRadioAsync(arguments);
        }
        catch (Exception error)
        {
            message = error.Message;
        }
        try
        {
            ShowRadio(await RunRadioAsync(new[] { "list" }), message);
        }
        catch (Exception error)
        {
            RadioStatusText.Text = message ?? error.Message;
        }
        RadioControls.IsEnabled = _mode == Mode.Ready;
        RadioList.IsEnabled = _mode == Mode.Ready;
    }

    private void ShowRadio(JsonElement status, string? message)
    {
        RadioList.Children.Clear();
        var stations = status.GetProperty("stations").EnumerateArray().ToList();
        foreach (var station in stations) RadioList.Children.Add(RadioRow(station));
        var ffmpeg = status.GetProperty("ffmpeg").ValueKind == JsonValueKind.String;
        RadioNewButton.IsEnabled = status.GetProperty("free_slots").GetArrayLength() > 0;
        RadioFfmpegButton.IsVisible = !ffmpeg;
        RadioStatusText.Text = message ?? (stations.Count == 0
            ? "No custom stations yet."
            : !ffmpeg
                ? "Building stations needs FFmpeg to encode the music. Install it from your package manager or locate the ffmpeg program."
                : status.GetProperty("out_of_date").GetBoolean()
                    ? "Changes are not built yet. Choose Build stations."
                    : "Built and on. The stations play from the next start.");
    }

    private Control RadioRow(JsonElement station)
    {
        var slot = station.GetProperty("slot").GetString()!;
        var name = station.GetProperty("name").GetString()!;
        var tracks = station.GetProperty("tracks").GetInt32();
        var missing = station.GetProperty("missing").GetArrayLength();
        var hasLogo = station.GetProperty("logo").ValueKind == JsonValueKind.String;
        var sources = station.GetProperty("sources").EnumerateArray().Select(s => s.GetString()!).ToArray();
        var nameBox = new TextBox { Text = name, MaxLength = 40, Width = 280, HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Left };
        async Task Rename()
        {
            var text = nameBox.Text?.Trim() ?? "";
            if (text.Length == 0 || text == name) { nameBox.Text = name; return; }
            await ChangeRadioAsync(new[] { "rename", slot, text }, "Updating…", $"Renamed to {text}.");
        }
        nameBox.LostFocus += async (_, _) => await Rename();
        nameBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) Focus(); };
        var keep = new CheckBox
        {
            IsChecked = station.GetProperty("mode").GetString() == "add",
            Content = new TextBlock { Text = "Keep the station's own songs too", FontSize = 12 },
        };
        keep.IsCheckedChanged += async (_, _) => await ChangeRadioAsync(
            new[] { "mode", slot, keep.IsChecked == true ? "add" : "replace" }, "Updating…",
            keep.IsChecked == true ? "Your songs join the station's own." : "Only your songs play on this station.");
        Button Action(string text, Func<Task> run)
        {
            var button = new Button { Content = text, Margin = new Avalonia.Thickness(0, 0, 8, 6) };
            button.Classes.Add("quiet");
            button.Click += async (_, _) => await run();
            return button;
        }
        var actions = new WrapPanel();
        actions.Children.Add(Action("Add folder", async () =>
        {
            var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
                { Title = $"Choose music folders for {name}", AllowMultiple = true });
            var paths = folders.Select(folder => folder.TryGetLocalPath()).OfType<string>().ToArray();
            if (paths.Length > 0)
                await ChangeRadioAsync(new[] { "add", slot }.Concat(paths).ToArray(), "Updating…", "Music added.");
        }));
        actions.Children.Add(Action("Add songs", async () =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = $"Choose songs for {name}", AllowMultiple = true,
                FileTypeFilter = new[]
                {
                    new FilePickerFileType("Music")
                        { Patterns = new[] { "*.mp3", "*.wav", "*.flac", "*.ogg", "*.m4a", "*.aac", "*.opus", "*.wma" } },
                    FilePickerFileTypes.All,
                },
            });
            var paths = files.Select(file => file.TryGetLocalPath()).OfType<string>().ToArray();
            if (paths.Length > 0)
                await ChangeRadioAsync(new[] { "add", slot }.Concat(paths).ToArray(), "Updating…", "Songs added.");
        }));
        if (sources.Length > 0)
            actions.Children.Add(Action("Clear music", () => ChangeRadioAsync(
                new[] { "remove", slot }.Concat(sources).ToArray(), "Updating…",
                "Music cleared. Your files were not touched.")));
        actions.Children.Add(Action(hasLogo ? "Change logo" : "Logo", async () =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = $"Choose a PNG logo for {name}",
                FileTypeFilter = new[] { new FilePickerFileType("PNG images") { Patterns = new[] { "*.png" } } },
            });
            var path = files.Select(file => file.TryGetLocalPath()).OfType<string>().FirstOrDefault();
            if (path is not null)
                await ChangeRadioAsync(new[] { "logo", slot, path }, "Updating…",
                    "Logo set. It is fitted into 210 by 100 pixels.");
        }));
        if (hasLogo)
            actions.Children.Add(Action("Own logo", () => ChangeRadioAsync(
                new[] { "logo", slot, "--clear" }, "Updating…", "The station's own logo is back.")));
        actions.Children.Add(Action("Delete", () => ChangeRadioAsync(new[] { "delete", slot }, "Updating…",
            "Station deleted; your music files were not touched. Build stations to apply.")));
        var details = $"Instead of {station.GetProperty("replaces").GetString()} · {tracks} {(tracks == 1 ? "song" : "songs")}"
            + (missing > 0 ? $" · {missing} missing" : "") + (hasLogo ? " · own logo" : "");
        var row = new StackPanel { Spacing = 4 };
        row.Children.Add(nameBox);
        row.Children.Add(new TextBlock
        {
            Text = details, FontSize = 12, TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Foreground = (Avalonia.Media.IBrush?)this.FindResource("MutedBrush"),
        });
        row.Children.Add(keep);
        row.Children.Add(actions);
        return row;
    }

    private async void RadioNew_Click(object? sender, RoutedEventArgs e) =>
        await ChangeRadioAsync(new[] { "create", "My Station" }, "Updating…",
            "Station added. Rename it, add a music folder or songs, then build stations.");

    private async void RadioBuild_Click(object? sender, RoutedEventArgs e)
    {
        PrimaryButton.IsEnabled = false;
        await ChangeRadioAsync(new[] { "build" },
            "Encoding your music and building the stations. Long playlists take a few minutes…",
            "Stations built. They play from the next start.");
        PrimaryButton.IsEnabled = _mode == Mode.Ready;
    }

    private async void RadioFfmpeg_Click(object? sender, RoutedEventArgs e)
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions { Title = "Choose the ffmpeg program" });
        var path = files.Select(file => file.TryGetLocalPath()).OfType<string>().FirstOrDefault();
        if (path is not null)
            await ChangeRadioAsync(new[] { "ffmpeg", path }, "Updating…", "FFmpeg found. Build stations when ready.");
    }

    private void Details_Click(object? sender, RoutedEventArgs e)
    {
        LogBox.IsVisible = !LogBox.IsVisible;
        DetailsButton.Content = LogBox.IsVisible ? "Hide details" : "Show details";
        if (LogBox.IsVisible) LogBox.Text = _log.ToString();
    }

    private void Cancel_Click(object? sender, RoutedEventArgs e) => _cancel?.Cancel();

    private void InstallAppleTools_Click(object? sender, RoutedEventArgs e) =>
        Installation.InstallAppleDeveloperTools();

    private async void CheckAppleTools_Click(object? sender, RoutedEventArgs e) => await LoadAsync();

    private void Saves_Click(object? sender, RoutedEventArgs e)
    {
        if (_installation is null) return;
        Directory.CreateDirectory(Path.Combine(_installation.StateRoot, "user"));
        Installation.Open(Path.Combine(_installation.StateRoot, "user"));
    }

    private void Logs_Click(object? sender, RoutedEventArgs e)
    {
        if (_installation is null) return;
        // The game's own logs (runtime.log) once it has run, else setup's.
        var gameLogs = Path.Combine(_installation.StateRoot, "logs");
        if (File.Exists(Path.Combine(gameLogs, "runtime.log")))
        {
            Installation.Open(gameLogs);
            return;
        }
        Directory.CreateDirectory(_installation.Logs);
        Installation.Open(_installation.Logs);
    }

    private void Report_Click(object? sender, RoutedEventArgs e) =>
        Installation.Open($"{Repository}/issues/new?template=bug.yml");

    private void GitHub_Click(object? sender, RoutedEventArgs e) => Installation.Open(Repository);

    public void Snapshot(string path, string? state)
    {
        Opened += async (_, _) =>
        {
            await Task.Delay(1500);
            if (state == "ready") ShowMode(Mode.Ready);
            if (state == "building")
            {
                ShowMode(Mode.Building);
                Progress.Value = 47;
                PercentText.Text = "47%";
                ProgressMessage.Text = "Building the game (812/2140)";
            }
            await Task.Delay(300);
            var size = new Avalonia.PixelSize((int)Bounds.Width, (int)Bounds.Height);
            using var bitmap = new Avalonia.Media.Imaging.RenderTargetBitmap(size);
            bitmap.Render(this);
            bitmap.Save(path);
            Close();
        };
    }

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        _cancel?.Cancel();
        base.OnClosing(e);
    }
}
