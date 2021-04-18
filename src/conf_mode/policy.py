#!/usr/bin/env python3
#
# Copyright (C) 2021 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from sys import exit

from vyos.config import Config
from vyos.configdict import dict_merge
from vyos.template import render_to_string
from vyos.util import dict_search
from vyos import ConfigError
from vyos import frr
from vyos import airbag
airbag.enable()

def get_config(config=None):
    if config:
        conf = config
    else:
        conf = Config()

    base = ['policy']
    policy = conf.get_config_dict(base, key_mangling=('-', '_'), get_first_key=True,
                                  no_tag_node_value_mangle=True)

    return policy

def verify(policy):
    if not policy:
        return None

    for policy_type in ['access_list', 'access_list6', 'as_path_list',
                        'community_list', 'extcommunity_list', 'large_community_list',
                        'prefix_list', 'prefix_list6', 'route_map']:
        # Bail out early and continue with next policy type
        if policy_type not in policy:
            continue

        # instance can be an ACL name/number, prefix-list name or route-map name
        for instance, instance_config in policy[policy_type].items():
            # If no rule was found within the instance ... sad, but we can leave
            # early as nothing needs to be verified
            if 'rule' not in instance_config:
                continue

            # human readable instance name (hypen instead of underscore)
            policy_hr = policy_type.replace('_', '-')
            for rule, rule_config in instance_config['rule'].items():
                mandatory_error = f'must be specified for "{policy_hr} {instance} rule {rule}"!'
                if 'action' not in rule_config:
                    raise ConfigError(f'Action {mandatory_error}')

                if policy_type == 'access_list':
                    if 'source' not in rule_config:
                        raise ConfigError(f'Source {mandatory_error}')

                    if int(instance) in range(100, 200) or int(instance) in range(2000, 2700):
                        if 'destination' not in rule_config:
                            raise ConfigError(f'Destination {mandatory_error}')

                if policy_type == 'access_list6':
                    if 'source' not in rule_config:
                        raise ConfigError(f'Source {mandatory_error}')

                if policy_type in ['as_path_list', 'community_list', 'extcommunity_list',
                                   'large_community_list']:
                    if 'regex' not in rule_config:
                        raise ConfigError(f'Regex {mandatory_error}')


    return None

def generate(policy):
    if not policy:
        policy['new_frr_config'] = ''
        return None

    policy['new_frr_config'] = render_to_string('frr/policy.frr.tmpl', policy)
    return None

def apply(policy):
    bgp_daemon = 'bgpd'
    zebra_daemon = 'zebra'

    # Save original configuration prior to starting any commit actions
    frr_cfg = frr.FRRConfig()

    # The route-map used for the FIB (zebra) is part of the zebra daemon
    frr_cfg.load_configuration(bgp_daemon)
    frr_cfg.modify_section(r'^bgp as-path access-list .*')
    frr_cfg.modify_section(r'^bgp community-list .*')
    frr_cfg.modify_section(r'^bgp extcommunity-list .*')
    frr_cfg.modify_section(r'^bgp large-community-list .*')
    frr_cfg.add_before('^line vty', policy['new_frr_config'])
    frr_cfg.commit_configuration(bgp_daemon)

    # The route-map used for the FIB (zebra) is part of the zebra daemon
    frr_cfg.load_configuration(zebra_daemon)
    frr_cfg.modify_section(r'^access-list .*')
    frr_cfg.modify_section(r'^ipv6 access-list .*')
    frr_cfg.modify_section(r'^ip prefix-list .*')
    frr_cfg.modify_section(r'^ipv6 prefix-list .*')
    frr_cfg.modify_section(r'^route-map .*')
    frr_cfg.add_before('^line vty', policy['new_frr_config'])
    frr_cfg.commit_configuration(zebra_daemon)

    # If FRR config is blank, rerun the blank commit x times due to frr-reload
    # behavior/bug not properly clearing out on one commit.
    if policy['new_frr_config'] == '':
        for a in range(5):
            frr_cfg.commit_configuration(zebra_daemon)

    # Save configuration to /run/frr/config/frr.conf
    frr.save_configuration()

    return None

if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        exit(1)
