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
DISTRO_CODENAME=$(
	grep "UBUNTU_CODENAME" /etc/os-release | cut -d= -f2 ||
		lsb_release -sc
)
DISTRO_VERSION=$(grep VERSION_ID /etc/os-release | cut -d= -f2 | tr -d '"')
mkdir -p "$BACKUP_DIR"

# =====================================================
# Check & install required tools: whiptail, jq
# =====================================================
for dep in whiptail jq; do
    if ! command -v "$dep" &>/dev/null; then
        # Ask user for installation
        read -rp "⚠️  '$dep' is required but not installed. Do you want to install it now? [y/N]: " choice
        if [[ "$choice" =~ ^[Yy]$ ]]; then
            apt-get update -y
            echo "Installing $dep..."
            apt-get install -y "$dep"
        else
            echo "❌ '$dep' is required to run this application. Exiting..."
            exit 1
        fi
    fi
done


clear

echo -e "\e[32m"
cat <<'EOF'
 __  __ _                     __  __       _
|  \/  (_)_ __ _ __ ___  _ __|  \/  | __ _| |_ ___
| |\/| | | '__| '__/ _ \| '__| |\/| |/ _` | __/ _ \
| |  | | | |  | | | (_) | |  | |  | | (_| | ||  __/
|_|  |_|_|_|  |_|  \___/|_|  |_|  |_|\__,_|\__\___|
EOF
echo -e "\e[0m"

# Intro banner
cat <<'EOF' 
───────────────────────────────────────────────────────────────
 🚀 MirrorMate — Your new BFF for blazing-fast mirrors!  
 ⚡ Switch effortlessly to the fastest open-source repositories  
 😎 GitHub: https://github.com/free-programmers/MirrorMate
───────────────────────────────────────────────────────────────
EOF

# User info display
echo -e "\n🔧 Running Script For \n"
printf "   👤 User             : %s\n"  "$TARGET_USER"
printf "   🏠 Home Directory   : %s\n"  "$TARGET_HOME"
printf "   🔁 Distro Codename  : %s\n"  "$DISTRO_CODENAME"
printf "   🗓  Release Version  : %s\n"  "$DISTRO_VERSION"
echo -e "\n───────────────────────────────────────────────────────────────\n"

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
fetch_mirrors() {
    local url="$1"
    
    # Download JSON to temp file
    TMP_JSON=$(mktemp)
    curl -sSL "$url" -o "$TMP_JSON" || { echo "❌ Failed to fetch mirrors from $url"; exit 1; }

    # Parse JSON into Bash array
    MIRRORS=()
	while IFS= read -r entry; do
		category=$(echo "$entry" | jq -r '.category')
		name=$(echo "$entry" | jq -r '.name')
		url=$(echo "$entry" | jq -r '.url')
		url=$(eval echo "$url")  # <- expands $DISTRO_CODENAME etc.
		MIRRORS+=("$category|$name|$url")
	done < <(jq -c '.[]' "$TMP_JSON")


    rm -f "$TMP_JSON"
}

# Fetch mirrors dynamically
MIRRORS_URL="https://raw.githubusercontent.com/free-programmers/MirrorMate/refs/heads/main/mirros/mirrors.json"
fetch_mirrors "$MIRRORS_URL"

# =====================================================
# Dependency check
# =====================================================
check_dependency() {
	local category="$1"
	case "$category" in
	Python) command -v pip &>/dev/null || {
		whiptail --msgbox "❌ pip not installed." 8 60
		exit 1
	} ;;
	Node.js) command -v npm &>/dev/null || {
		whiptail --msgbox "❌ npm not installed." 8 60
		exit 1
	} ;;
	Go) command -v go &>/dev/null || {
		whiptail --msgbox "❌ Go not installed." 8 60
		exit 1
	} ;;
	Docker) command -v docker &>/dev/null || {
		whiptail --msgbox "❌ Docker not installed." 8 60
		exit 1
	} ;;
	APT) command -v apt-get &>/dev/null || {
		whiptail --msgbox "❌ apt-get not found." 8 60
		exit 1
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
	whiptail --title "MirrorMate" --menu "Select Mirror Type:" 20 70 10 "${categories[@]}" 3>&1 1>&2 2>&3
}

# =====================================================
# Mirror Menu
# =====================================================
mirror_menu() {
    local category="$1"
    local items=()

    for entry in "${MIRRORS[@]}"; do
        IFS='|' read -r cat name url <<< "$entry"
        [[ "$cat" != "$category" ]] && continue

        # For APT mirrors, just grab the first line (first "deb" entry)
        if [[ "$cat" == "APT" ]]; then
            local first_url
            first_url=$(echo "$url" | head -n1 | awk '{print $2}') # take only the URL part
            items+=("$name" "$first_url")
        else
            # Normal case (Python, Node, Docker, etc.)
            items+=("$name" "$url")
        fi
    done

    items+=("back" "Go Back")

    whiptail --title "$category Mirrors" \
        --menu "Select a mirror:" 20 110 10 \
        "${items[@]}" 3>&1 1>&2 2>&3
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
