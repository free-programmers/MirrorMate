#!/bin/bash
clear

# =====================================================
#  MirrorMate - Dynamic Open Source Mirror Switcher
#  github: https://github.com/free-programmers/MirrorMate
# =====================================================

if [[ $EUID -ne 0 ]]; then
    echo "❌ Please run with sudo"
    exit 1
fi

BACKUP_DIR="/var/lib/mirrormate/backup"
mkdir -p "$BACKUP_DIR"

# Install dependencies if missing
if ! command -v whiptail &>/dev/null; then
    echo "Installing whiptail..."
    apt-get update && apt-get install -y whiptail
fi

if ! command -v figlet &>/dev/null; then
    echo "Installing figlet..."
    apt-get update && apt-get install -y figlet
fi

if ! command -v lolcat &>/dev/null; then
    echo "Installing lolcat..."
    apt-get update
    apt-get install -y ruby
    gem install lolcat
fi

clear
figlet -f standard MirrorMate | lolcat
cat <<'EOF'
/*
    MirrorMate — Your new BFF for switching to the fastest open-source mirrors without breaking a sweat! 😎✨
    github: https://github.com/free-programmers/MirrorMate
*/
EOF
sleep 2

# =====================================================
# Mirror list
# Format: category|display name|mirror URL
# =====================================================
MIRRORS=(
    # Python
    "Python|PyPI - Runflare (Iran)|https://mirror-pypi.runflare.com/simple"
    "Python|PyPI - Tsinghua (China)|https://pypi.tuna.tsinghua.edu.cn/simple"
    "Python|PyPI - Aliyun (China)|https://mirrors.aliyun.com/pypi/simple/"
    "Python|PyPI - IranRepo (IR ICT) (Iran)|https://repo.ito.gov.ir/python/"
    "Python|PyPI - Mecan (AhmadRafiee) (Iran)|https://repo.mecan.ir/repository/pypi/"
    "Python|PyPI - USTC (China)|https://pypi.mirrors.ustc.edu.cn/simple/"
    "Python|PyPI - Fastly (Global)|https://pypi.org/simple"

    # Node.js
    "Node.js|NPM - RunFlare (Iran)|https://mirror-npm.runflare.com"
    "Node.js|NPM - Tsinghua (China)|https://registry.npmmirror.com"
    "Node.js|NPM - Aliyun (China)|https://registry.npm.taobao.org"
    "Node.js|NPM - IranRepo (IR ICT) (Iran)|https://repo.ito.gov.ir/npm/"
    "Node.js|NPM - Yarnpkg (Global)|https://registry.yarnpkg.com"

    # Docker
    "Docker|Docker Hub - Runflare (Iran)|https://mirror-docker.runflare.com"
    "Docker|Docker Hub - Focker (Iran)|https://focker.ir"
    "Docker|Docker Hub - ArvanCloud (Iran)|https://docker.arvancloud.ir/"
    "Docker|Docker Hub - Hamravesh (Iran)|https://hub.hamdocker.ir/"
    "Docker|Docker Hub - IranServer (Iran)|https://docker.iranserver.com/"
    "Docker|Docker Hub - USTC (China)|https://docker.mirrors.ustc.edu.cn/"
    "Docker|Docker Hub - MobinHost (Iran)|https://docker.mobinhost.com/"
    "Docker|Docker Hub - Docker Official (Global)|https://registry-1.docker.io"

    # Go
    "Go|GoProxy - Aliyun (China)|https://mirrors.aliyun.com/goproxy/"
    "Go|GoProxy - Golang Official (Global)|https://proxy.golang.org"

    # APT
    "APT|Ubuntu - ArvanCloud (Iran)|deb http://mirror.arvancloud.ir/ubuntu/ noble main restricted universe multiverse\ndeb http://mirror.arvancloud.ir/ubuntu/ noble-updates main restricted universe multiverse\ndeb http://mirror.arvancloud.ir/ubuntu/ noble-security main restricted universe multiverse"
    "APT|Ubuntu - Tsinghua (China)|deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble main restricted universe multiverse\ndeb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-updates main restricted universe multiverse\ndeb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-security main restricted universe multiverse"
    "APT|Ubuntu - MobinHost (Iran)|deb https://ubuntu.mobinhost.com/ubuntu/ noble main restricted universe multiverse\ndeb https://ubuntu.mobinhost.com/ubuntu/ noble-updates main restricted universe multiverse\ndeb https://ubuntu.mobinhost.com/ubuntu/ noble-security main restricted universe multiverse"
    "APT|Ubuntu - IranRepo (IR ICT) (Iran)|deb https://repo.ito.gov.ir/ubuntu/ jammy main restricted universe multiverse\ndeb https://repo.ito.gov.ir/ubuntu jammy-updates main restricted universe multiverse\ndeb https://repo.ito.gov.ir/ubuntu/ jammy-security main restricted universe multiverse"
    "APT|Ubuntu - Official (Global)|deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse\ndeb http://archive.ubuntu.com/ubuntu jammy-updates main restricted universe multiverse\ndeb http://archive.ubuntu.com/ubuntu jammy-security main restricted universe multiverse"
)


# =====================================================
# Backup functions
# =====================================================
backup_config() {
    back up mirros into $BACKUP_DIR
    category="$1"
    case "$category" in
        Python)
            val=$(pip config get global.index-url 2>/dev/null)
            [[ -n "$val" ]] && echo "$val" > "$BACKUP_DIR/pip_index_url"
            ;;
        Node.js)
            val=$(npm config get registry 2>/dev/null)
            [[ -n "$val" ]] && echo "$val" > "$BACKUP_DIR/npm_registry"
            ;;
        Docker)
            if [[ -f /etc/docker/daemon.json ]]; then
                cp /etc/docker/daemon.json "$BACKUP_DIR/docker_daemon.json"
            fi
            ;;
        Go)
            val=$(go env GOPROXY 2>/dev/null)
            [[ -n "$val" ]] && echo "$val" > "$BACKUP_DIR/go_proxy"
            ;;
        APT)
            cp /etc/apt/sources.list "$BACKUP_DIR/sources.list" 2>/dev/null
            ;;
    esac
}

restore_config() {
    category="$1"
    case "$category" in
        Python) [[ -f "$BACKUP_DIR/pip_index_url" ]] && pip config set global.index-url "$(cat "$BACKUP_DIR/pip_index_url")" ;;
        Node.js) [[ -f "$BACKUP_DIR/npm_registry" ]] && npm config set registry "$(cat "$BACKUP_DIR/npm_registry")" ;;
        Docker) [[ -f "$BACKUP_DIR/docker_daemon.json" ]] && cp "$BACKUP_DIR/docker_daemon.json" /etc/docker/daemon.json && command -v docker &>/dev/null && systemctl is-active --quiet docker && systemctl restart docker ;;
        Go) [[ -f "$BACKUP_DIR/go_proxy" ]] && go env -w GOPROXY="$(cat "$BACKUP_DIR/go_proxy")" ;;
        APT) [[ -f "$BACKUP_DIR/sources.list" ]] && cp "$BACKUP_DIR/sources.list" /etc/apt/sources.list && apt-get update ;;
    esac
}


check_dependency() {
    local category="$1"
    case "$category" in
        Python)
            if ! command -v pip &>/dev/null; then
                whiptail --msgbox "❌ pip is not installed.\nPlease install Python pip before setting PyPI mirrors." 8 60
                return 1
            fi
            ;;
        Node.js)
            if ! command -v npm &>/dev/null; then
                whiptail --msgbox "❌ npm is not installed.\nPlease install Node.js before setting NPM mirrors." 8 60
                return 1
            fi
            ;;
        Docker)
            if ! command -v docker &>/dev/null; then
                whiptail --msgbox "❌ Docker is not installed.\nPlease install Docker before setting Docker mirrors." 8 60
                return 1
            fi
            ;;
        Go)
            if ! command -v go &>/dev/null; then
                whiptail --msgbox "❌ Go is not installed.\nPlease install Go before setting Go mirrors." 8 60
                return 1
            fi
            ;;
        APT)
            if ! command -v apt-get &>/dev/null; then
                whiptail --msgbox "❌ apt-get is not available.\nThis script requires apt-based system to set APT mirrors." 8 60
                return 1
            fi
            ;;
        *)
            return 0
            ;;
    esac
    return 0
}


# =====================================================
# Apply functions
# =====================================================
apply_mirror() {
    category="$1"
    url="$2"

    # Check dependency first
    if ! check_dependency "$category"; then
        return 1
    fi

    case "$category" in
        Python)
            pip config set global.break-system-packages true
            pip config set global.index-url "$url"
            ;;
        Node.js)
            npm config set registry "$url"
            ;;
        Docker)
            mkdir -p /etc/docker
            echo "{\"registry-mirrors\": [\"$url\"]}" > /etc/docker/daemon.json
            if systemctl is-active --quiet docker; then
                systemctl restart docker
            fi
            ;;
        Go)
            go env -w GOPROXY="$url"
            ;;
        APT)
            echo -e "$url" > /etc/apt/sources.list.d/mirrormate.list
            apt-get update
            ;;
    esac
}


# =====================================================
# Menu functions
# =====================================================
main_menu() {
    local categories=()
    local seen=()
    for entry in "${MIRRORS[@]}"; do
        IFS='|' read -r category _ _ <<< "$entry"
        if [[ ! " ${seen[*]} " =~ " ${category} " ]]; then
            categories+=("$category" "$category mirrors list")
            seen+=("$category")
        fi
    done
    categories+=("Restore" "Restore previous settings")
    categories+=("Quit" "Exit")
    whiptail --title "MirrorMate - Open Source Mirror Switcher" --menu "Select a category:" 20 70 10 "${categories[@]}" 3>&1 1>&2 2>&3
}

mirror_menu() {
    local category="$1"
    local items=()
    for entry in "${MIRRORS[@]}"; do
        IFS='|' read -r cat name _ <<< "$entry"
        if [[ "$cat" == "$category" ]]; then
            items+=("$name" "$name")
        fi
    done
    items+=("back" "Go Back")
    whiptail --title "$category Mirrors" --menu "Select a mirror:" 20 70 10 "${items[@]}" 3>&1 1>&2 2>&3
}

restore_menu() {
    local items=()
    local seen=()
    for entry in "${MIRRORS[@]}"; do
        IFS='|' read -r category _ _ <<< "$entry"
        if [[ ! " ${seen[*]} " =~ " ${category} " ]]; then
            items+=("$category" "Restore $category settings")
            seen+=("$category")
        fi
    done
    items+=("all" "Restore All")
    items+=("back" "Go Back")
    whiptail --title "Restore Settings" --menu "Select to restore:" 20 70 10 "${items[@]}" 3>&1 1>&2 2>&3
}

# =====================================================
# Ensure initial backup exists
# =====================================================
if [[ ! -f "$BACKUP_DIR/.initial_backup_done" ]]; then
    echo "📦 Performing initial backup..."
    for entry in "${MIRRORS[@]}"; do
        IFS='|' read -r category _ _ <<< "$entry"
        backup_config "$category"
    done
    touch "$BACKUP_DIR/.initial_backup_done"
fi

# =====================================================
# Main loop
# =====================================================
while true; do
    choice=$(main_menu) || exit 0
    case "$choice" in
        Quit) exit 0 ;;
        Restore)
            rchoice=$(restore_menu)
            case "$rchoice" in
                all)
                    for entry in "${MIRRORS[@]}"; do
                        IFS='|' read -r category _ _ <<< "$entry"
                        restore_config "$category"
                    done
                    whiptail --msgbox "✅ All settings restored from backup." 8 60
                    ;;
                back) continue ;;
                *)
                    restore_config "$rchoice"
                    whiptail --msgbox "✅ $rchoice settings restored from backup." 8 60
                    ;;
            esac
            ;;
        *)
            while true; do
                mchoice=$(mirror_menu "$choice")
                [[ "$mchoice" == "back" ]] && break
                for entry in "${MIRRORS[@]}"; do
                    IFS='|' read -r category name url <<< "$entry"
                    if [[ "$category" == "$choice" && "$name" == "$mchoice" ]]; then
                        backup_config "$category"
                        apply_mirror "$category" "$url"
                        next_action=$(whiptail --title "Mirror Set" --menu "✅ Mirror set successfully!\nWhat do you want to do next?" 10 60 2 \
                        "1" "Exit" \
                        "2" "Back to Main Menu" 3>&1 1>&2 2>&3)
                        case "$next_action" in
                            1) echo "👋 Goodbye!"; exit 0 ;;
                            2) break 2 ;;
                            *) break 2 ;;
                        esac
                    fi
                done
            done
            ;;
    esac
done
