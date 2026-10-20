def test_agents_package_importable():
    import sdlc_agents.machine as machine

    assert hasattr(machine, "next_action")
