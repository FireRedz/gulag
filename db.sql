# Remove pre-existing tables.
drop table if exists stats;
drop table if exists users;
drop table if exists scores_rx;
drop table if exists scores_vn;
drop table if exists maps;
drop table if exists friendships;
drop table if exists channels;

create table users
(
	id int(11) auto_increment
		primary key,
	name varchar(32) not null,
	name_safe varchar(32) not null,
	priv int(11) default 1 null,
	pw_hash char(60) null,
	country char(2) default 'xx' not null,
	silence_end int(11) default 0 not null,
	email varchar(254) not null,
	constraint(11) users_email_uindex
		unique (email),
	constraint(11) users_name_safe_uindex
		unique (name_safe),
	constraint(11) users_name_uindex
		unique (name)
);

create table user_hashes
(
	id int(11) auto_increment
		primary key,
	osupath char(32) not null,
	adapters char(32) not null,
	uninstall_id char(32) not null,
	disk_serial char(32) not null,
	constraint(11) user_hashes_users_id_fk
		foreign key (id) references users (id)
			on update cascade on delete cascade
);

# With this I decided to make a naming scheme rather
# than something nescessarily 'readable' or pretty, I
# think in practice this will be much easier to use
# and memorize quickly compared to other schemes.
# Syntax is simply: stat_rxmode_osumode
create table stats
(
	id int(11) auto_increment
		primary key,
	tscore_vn_std int(11) default 0 not null,
	tscore_vn_taiko int(11) default 0 not null,
	tscore_vn_catch int(11) default 0 not null,
	tscore_vn_mania int(11) default 0 not null,
	tscore_rx_std int(11) default 0 not null,
	tscore_rx_taiko int(11) default 0 not null,
	tscore_rx_catch int(11) default 0 not null,
	rscore_vn_std int(11) default 0 not null,
	rscore_vn_taiko int(11) default 0 not null,
	rscore_vn_catch int(11) default 0 not null,
	rscore_vn_mania int(11) default 0 not null,
	rscore_rx_std int(11) default 0 not null,
	rscore_rx_taiko int(11) default 0 not null,
	rscore_rx_catch int(11) default 0 not null,
	pp_vn_std smallint(6) default 0 not null,
	pp_vn_taiko smallint(6) default 0 not null,
	pp_vn_catch smallint(6) default 0 not null,
	pp_vn_mania smallint(6) default 0 not null,
	pp_rx_std smallint(6) default 0 not null,
	pp_rx_taiko smallint(6) default 0 not null,
	pp_rx_catch smallint(6) default 0 not null,
	plays_vn_std int(11) default 0 not null,
	plays_vn_taiko int(11) default 0 not null,
	plays_vn_catch int(11) default 0 not null,
	plays_vn_mania int(11) default 0 not null,
	plays_rx_std int(11) default 0 not null,
	plays_rx_taiko int(11) default 0 not null,
	plays_rx_catch int(11) default 0 not null,
	playtime_vn_std int(11) default 0 not null,
	playtime_vn_taiko int(11) default 0 not null,
	playtime_vn_catch int(11) default 0 not null,
	playtime_vn_mania int(11) default 0 not null,
	playtime_rx_std int(11) default 0 not null,
	playtime_rx_taiko int(11) default 0 not null,
	playtime_rx_catch int(11) default 0 not null,
	acc_vn_std float(5,3) default 0.000 not null,
	acc_vn_taiko float(5,3) default 0.000 not null,
	acc_vn_catch float(5,3) default 0.000 not null,
	acc_vn_mania float(5,3) default 0.000 not null,
	acc_rx_std float(5,3) default 0.000 not null,
	acc_rx_taiko float(5,3) default 0.000 not null,
	acc_rx_catch float(5,3) default 0.000 not null,
	maxcombo_vn_std int(11) default 0 not null,
	maxcombo_vn_taiko int(11) default 0 not null,
	maxcombo_vn_catch int(11) default 0 not null,
	maxcombo_vn_mania int(11) default 0 not null,
	maxcombo_rx_std int(11) default 0 not null,
	maxcombo_rx_taiko int(11) default 0 not null,
	maxcombo_rx_catch int(11) default 0 not null,
	constraint(11) stats_users_id_fk
		foreign key (id) references users (id)
			on update cascade on delete cascade
);

create table scores_rx
(
	id int(11) auto_increment
		primary key,
	map_md5 char(32) not null,
	score int(11) not null,
	pp float(7,3) not null,
	acc float(6,3) not null,
	max_combo int(11) not null,
	mods int(11) not null,
	n300 int(11) not null,
	n100 int(11) not null,
	n50 int(11) not null,
	nmiss int(11) not null,
	ngeki int(11) not null,
	nkatu int(11) not null,
	grade varchar(2) default 'N' not null,
	status tinyint(11) not null,
	game_mode tinyint(11) not null,
	play_time int(11) not null,
	client_flags int(11) not null,
	userid int(11) not null,
	perfect tinyint(1) not null
);

create table scores_vn
(
	id int(11) auto_increment
		primary key,
	map_md5 char(32) not null,
	score int(11) not null,
	pp float(7,3) not null,
	acc float(6,3) not null,
	max_combo int(11) not null,
	mods int(11) not null,
	n300 int(11) not null,
	n100 int(11) not null,
	n50 int(11) not null,
	nmiss int(11) not null,
	ngeki int(11) not null,
	nkatu int(11) not null,
	grade varchar(2) default 'N' not null,
	status tinyint(11) not null,
	game_mode tinyint(11) not null,
	play_time int(11) not null,
	client_flags int(11) not null,
	userid int(11) not null,
	perfect tinyint(1) not null
);

# TODO: find the real max lengths for strings
create table maps
(
	id int(11) not null
	    primary key,
	set_id int(11) not null,
	status int(11) not null,
	md5 char(32) not null,
	artist varchar(128) not null,
	title varchar(128) not null,
	version varchar(128) not null,
	creator varchar(128) not null,
	last_update datetime null comment 'will be NOT NULL in future',
	frozen tinyint(11) default 1 null,
	mode tinyint(1) default 0 not null,
	bpm float(9,2) default 0.00 not null,
	cs float(4,2) default 0.00 not null,
	od float(4,2) default 0.00 not null,
	ar float(4,2) default 0.00 not null,
	hp float(4,2) default 0.00 not null,
	diff float(6,3) default 0.000 not null,
	constraint(11) maps_id_uindex
		unique (id),
	constraint(11) maps_md5_uindex
		unique (md5)
);

create table friendships
(
  	user1 int(11) not null,
	user2 int(11) not null,
	primary key (user1, user2)
);

create table channels
(
	id int(11) auto_increment
		primary key,
	name varchar(32) not null,
	topic varchar(256) not null,
	read_priv int(11) default 1 not null,
	write_priv int(11) default 2 not null,
	auto_join tinyint(1) default 0 null,
	constraint(11) channels_name_uindex
		unique (name)
);

# Insert vital stuff, such as bot user & basic channels.

insert into users (id, name, name_safe, priv, country, silence_end, email, pw_hash)
values (1, 'Aika', 'aika', 1, 'ca', 0, 'aika@gulag.ca',
        '_______________________my_cool_bcrypt_______________________');

insert into stats (id) values (1);

# userid 2 is reserved for ppy in osu!, and the
# client will not allow users to pm this id.
# If you want this, simply remove these two lines.
alter table users auto_increment = 3;
alter table stats auto_increment = 3;

insert into channels (name, topic, read_priv, write_priv, auto_join)
values ('#osu', 'General discussion.', 1, 2, true),
	   ('#announce', 'Exemplary performance and public announcements.', 1, 2, true),
	   ('#lobby', 'Multiplayer lobby discussion room.', 1, 2, false);
