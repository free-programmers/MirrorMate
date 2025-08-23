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

# Detect the real user (who invoked sudo)
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME=$(eval echo "~$TARGET_USER")

BACKUP_DIR="/var/lib/mirrormate/backup"
mkdir -p "$BACKUP_DIR"
DISTRO_CODENAME=$(
	grep "UBUNTU_CODENAME" /etc/os-release | cut -d= -f2 ||
		lsb_release -sc
)
DISTRO_VERSION=$(grep VERSION_ID /etc/os-release | cut -d= -f2 | tr -d '"')

# =====================================================
# Install dependencies if missing
# =====================================================

for dep in whiptail figlet lolcat; do
	if ! command -v $dep &>/dev/null; then
		echo "$dep is not installed on machine, trying to install it"
		apt-get update
		echo "Installing $dep..."
		if [[ $dep == "lolcat" ]]; then
			apt-get install -y ruby
			gem install lolcat
		else
			apt-get install -y $dep
		fi
	fi
done

clear

# Fancy title
figlet -f slant "MirrorMate" | lolcat

# Intro banner
cat <<'EOF' | lolcat
/*───────────────────────────────────────────────────────────────
    🚀 MirrorMate — Your new BFF for supercharging your system!  
    ⚡ Switch to the fastest open-source mirrors, stress-free!  
    😎✨ GitHub: https://github.com/free-programmers/MirrorMate
───────────────────────────────────────────────────────────────*/
EOF

# User info display
echo -e "\n🔧 Running Script for:\n"
echo -e "   👤 User:          $TARGET_USER"
echo -e "   🏠 Home Directory: $TARGET_HOME"
echo -e "   🔁 Distro Codename: $DISTRO_CODENAME"
echo -e "   🗓  Release Version: $DISTRO_VERSION\n"

sleep 2
# =====================================================
# Load user environment
# =====================================================
load_user_env() {
	TARGET_USER_HOME=$(eval echo "~$TARGET_USER")

	# only source if file exists
	[[ -f "$TARGET_USER_HOME/.profile" ]] && source "$TARGET_USER_HOME/.profile" 2>/dev/null
	[[ -f "$TARGET_USER_HOME/.bashrc" ]] && source "$TARGET_USER_HOME/.bashrc" 2>/dev/null
}

load_user_env

# =====================================================
# Mirror list
# Format: category|display name|mirror URL or sources
# =====================================================
MIRRORS=(
	"Python|PyPI - Runflare (Iran)|https://mirror-pypi.runflare.com/simple"
	"Python|PyPI - Tsinghua (China)|https://pypi.tuna.tsinghua.edu.cn/simple"
	"Python|PyPI - Aliyun (China)|https://mirrors.aliyun.com/pypi/simple/"
	"Python|PyPI - IranRepo (IR ICT) (Iran)|https://repo.ito.gov.ir/python/"
	"Python|PyPI - Mecan (AhmadRafiee) (Iran)|https://repo.mecan.ir/repository/pypi/"
	"Python|PyPI - USTC (China)|https://pypi.mirrors.ustc.edu.cn/simple/"
	"Python|PyPI - Fastly (Global)|https://pypi.org/simple"
	"Python|PyPI - sustech.edu (China)|https://mirrors.sustech.edu.cn/pypi/web/simple"
	"Python|PyPI - cloud.tencent.com (China)|https://mirrors.cloud.tencent.com/pypi/simple/"

	"Node.js|NPM - RunFlare (Iran)|https://mirror-npm.runflare.com"
	"Node.js|NPM - Tsinghua (China)|https://registry.npmmirror.com"
	"Node.js|NPM - Aliyun (China)|https://registry.npm.taobao.org"
	"Node.js|NPM - IranRepo (IR ICT) (Iran)|https://repo.ito.gov.ir/npm/"
	"Node.js|NPM - Yarnpkg (Global)|https://registry.yarnpkg.com"

	"Docker|Docker Hub - Docker Official (Global)|https://registry-1.docker.io"
	"Docker|Docker Hub - ArvanCloud (Iran)|https://docker.arvancloud.ir"
	"Docker|Docker Hub - Hamravesh (Iran)|https://hub.hamdocker.ir"
	"Docker|Docker Hub - Focker (Iran)|https://focker.ir"
	"Docker|Docker Hub - Runflare (Iran)|https://mirror-docker.runflare.com"
	"Docker|Docker Hub - IranServer (Iran)|https://docker.iranserver.com"
	"Docker|Docker Hub - USTC (China)|https://docker.mirrors.ustc.edu.cn"
	"Docker|Docker Hub - MobinHost (Iran)|https://docker.mobinhost.com"

	"Go|GoProxy - Aliyun (China)|https://mirrors.aliyun.com/goproxy/"
	"Go|GoProxy - Golang Official (Global)|https://proxy.golang.org"

	"APT|Ubuntu - ArvanCloud (Iran)|deb http://mirror.arvancloud.ir/ubuntu/ $DISTRO_CODENAME main restricted universe multiverse
    deb http://mirror.arvancloud.ir/ubuntu/ ${DISTRO_CODENAME}-updates main restricted universe multiverse
    deb http://mirror.arvancloud.ir/ubuntu/ ${DISTRO_CODENAME}-security main restricted universe multiverse"

	"APT|Ubuntu - Tsinghua (China)|deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ $DISTRO_CODENAME main restricted universe multiverse
    deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ ${DISTRO_CODENAME}-updates main restricted universe multiverse
    deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ ${DISTRO_CODENAME}-security main restricted universe multiverse"

	"APT|Ubuntu - MobinHost (Iran)|deb https://ubuntu.mobinhost.com/ubuntu/ $DISTRO_CODENAME main restricted universe multiverse
    deb https://ubuntu.mobinhost.com/ubuntu/ ${DISTRO_CODENAME}-updates main restricted universe multiverse
    deb https://ubuntu.mobinhost.com/ubuntu/ ${DISTRO_CODENAME}-security main restricted universe multiverse"

	"APT|Ubuntu - IranRepo (IR ICT) (Iran)|deb https://repo.ito.gov.ir/ubuntu/ $DISTRO_CODENAME main restricted universe multiverse
    deb https://repo.ito.gov.ir/ubuntu ${DISTRO_CODENAME}-updates main restricted universe multiverse
    deb https://repo.ito.gov.ir/ubuntu/ ${DISTRO_CODENAME}-security main restricted universe multiverse"

	"APT|Ubuntu - Official (Global)|deb http://archive.ubuntu.com/ubuntu $DISTRO_CODENAME main restricted universe multiverse
    deb http://archive.ubuntu.com/ubuntu ${DISTRO_CODENAME}-updates main restricted universe multiverse
    deb http://archive.ubuntu.com/ubuntu ${DISTRO_CODENAME}-security main restricted universe multiverse"

)

# =====================================================
# Dependency check
# =====================================================
check_dependency() {
	local category="$1"
	case "$category" in
	Python) command -v pip &>/dev/null || {
		whiptail --msgbox "❌ pip not installed." 8 60
		return 1
	} ;;
	Node.js) command -v npm &>/dev/null || {
		whiptail --msgbox "❌ npm not installed." 8 60
		return 1
	} ;;
	Go) command -v go &>/dev/null || {
		whiptail --msgbox "❌ Go not installed." 8 60
		return 1
	} ;;
	Docker) command -v docker &>/dev/null || {
		whiptail --msgbox "❌ Docker not installed." 8 60
		return 1
	} ;;
	APT) command -v apt-get &>/dev/null || {
		whiptail --msgbox "❌ apt-get not found." 8 60
		return 1
	} ;;
	esac
}

# =====================================================
# Backup & Restore
# =====================================================
backup_config() {
	category="$1"
	case "$category" in
	Python) [[ -f "$TARGET_HOME/.config/pip/pip.conf" ]] && cp "$TARGET_HOME/.config/pip/pip.conf" "$BACKUP_DIR/pip.conf" ;;
	Node.js) [[ -f "$TARGET_HOME/.npmrc" ]] && cp "$TARGET_HOME/.npmrc" "$BACKUP_DIR/npmrc" ;;
	Go) [[ -f "$TARGET_HOME/.config/go/env" ]] && cp "$TARGET_HOME/.config/go/env" "$BACKUP_DIR/go_env" ;;
	Docker) [[ -f /etc/docker/daemon.json ]] && cp /etc/docker/daemon.json "$BACKUP_DIR/docker_daemon.json" ;;
	APT) [[ -f /etc/apt/sources.list ]] && cp /etc/apt/sources.list "$BACKUP_DIR/sources.list" ;;
	esac
}

restore_config() {
	category="$1"
	case "$category" in
	Python) [[ -f "$BACKUP_DIR/pip.conf" ]] && cp "$BACKUP_DIR/pip.conf" "$TARGET_HOME/.config/pip/pip.conf" ;;
	Node.js) [[ -f "$BACKUP_DIR/npmrc" ]] && cp "$BACKUP_DIR/npmrc" "$TARGET_HOME/.npmrc" ;;
	Go) [[ -f "$BACKUP_DIR/go_env" ]] && cp "$BACKUP_DIR/go_env" "$TARGET_HOME/.config/go/env" ;;
	Docker) [[ -f "$BACKUP_DIR/docker_daemon.json" ]] && cp "$BACKUP_DIR/docker_daemon.json" /etc/docker/daemon.json && systemctl restart docker ;;
	APT) [[ -f "$BACKUP_DIR/sources.list" ]] && cp "$BACKUP_DIR/sources.list" /etc/apt/sources.list && apt-get update ;;
	esac
}

get_ping() {
	local url="$1"
	# Extract host from URL
	local host
	host=$(echo "$url" | awk -F[/:] '{print $4}')
	# Ping once and get average round-trip time
	if ping -c 1 -W 1 "$host" &>/dev/null; then
		ping -c 1 -W 1 "$host" | tail -1 | awk -F '/' '{print $5 " ms"}'
	else
		echo "unreachable"
	fi
}

# =====================================================
# Apply mirrors
# =====================================================
apply_mirror() {
	category="$1"
	url="$2"

	if ! check_dependency "$category"; then return 1; fi

	case "$category" in
	Python)
		mkdir -p "$TARGET_HOME/.config/pip"
		sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" PATH="$PATH" pip config --user set global.index-url "$url"
		;;
	Node.js)
		sudo -u "$TARGET_USER" npm config set registry "$url" --location=user
		;;
	Go)
		sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" PATH="$PATH" go env -w GOPROXY="$url"
		;;
	Docker)
		mkdir -p /etc/docker &&
			cat >/etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["$url"],
  "registry-mirrors": ["$url"]
}
EOF
		sudo docker logout
		sudo systemctl restart docker
		;;
	APT)
		echo -e "$url" >/etc/apt/sources.list.d/mirrormate.list
		apt-get update
		;;
	esac
}

# =====================================================
# Menus
# =====================================================
main_menu() {
	local categories=()
	local seen=()
	for entry in "${MIRRORS[@]}"; do
		IFS='|' read -r category _ _ <<<"$entry"
		if [[ ! " ${seen[*]} " =~ " ${category} " ]]; then
			categories+=("$category" "$category mirrors list")
			seen+=("$category")
		fi
	done
	categories+=("Restore" "Restore previous settings")
	categories+=("Quit" "Exit")
	whiptail --title "MirrorMate" --menu "Select a category:" 20 50 10 "${categories[@]}" 3>&1 1>&2 2>&3
}
# =====================================================
# Mirror Menu
# =====================================================

mirror_menu() {
	local category="$1"
	local items=()

	for entry in "${MIRRORS[@]}"; do
		IFS='|' read -r cat name url <<<"$entry"
		[[ "$cat" == "$category" ]] || continue
		ping_time=$(get_ping "$url")
		items+=("$name" "$Ping: $ping_time")
	done
	items+=("back" "Go Back")
	whiptail --title "$category Mirrors" --menu "Select a mirror (ping shown):" 20 60 10 "${items[@]}" 3>&1 1>&2 2>&3
}

restore_menu() {
	local items=()
	local seen=()
	for entry in "${MIRRORS[@]}"; do
		IFS='|' read -r category _ _ <<<"$entry"
		[[ ! " ${seen[*]} " =~ " ${category} " ]] && items+=("$category" "Restore $category settings") && seen+=("$category")
	done
	items+=("all" "Restore All")
	items+=("back" "Go Back")
	whiptail --title "Restore Settings" --menu "Select to restore:" 20 60 10 "${items[@]}" 3>&1 1>&2 2>&3
}

# =====================================================
# Initial backup
# =====================================================
[[ ! -f "$BACKUP_DIR/.initial_backup_done" ]] && {
	echo "📦 Performing initial backup..."
	for entry in "${MIRRORS[@]}"; do
		IFS='|' read -r category _ _ <<<"$entry"
		backup_config "$category"
	done
	touch "$BACKUP_DIR/.initial_backup_done"
}

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
				IFS='|' read -r category _ _ <<<"$entry"
				restore_config "$category"
			done
			whiptail --msgbox "✅ All settings restored from backup." 8 60
			;;
		back) continue ;;
		*) restore_config "$rchoice" && whiptail --msgbox "✅ $rchoice settings restored from backup." 8 60 ;;
		esac
		;;
	*)
		while true; do
			echo "Calculating Ping for $choice, please wait ..."
			mchoice=$(mirror_menu "$choice")
			[[ "$mchoice" == "back" ]] && break
			for entry in "${MIRRORS[@]}"; do
				IFS='|' read -r category name url <<<"$entry"
				if [[ "$category" == "$choice" && "$name" == "$mchoice" ]]; then
					backup_config "$category"
					apply_mirror "$category" "$url"
					next_action=$(whiptail --title "Mirror Set" --menu "✅ Mirror set successfully!\nWhat next?" 10 80 2 \
						"1" "Exit" \
						"2" "Back to Main Menu" 3>&1 1>&2 2>&3)
					case "$next_action" in
					1)
						echo "👋 Goodbye!"
						exit 0
						;;
					2) break 2 ;;
					*) break 2 ;;
					esac
				fi
			done
		done
		;;
	esac
done
