<?php
namespace App\Svc;

class Service
{
    private Repo $repo;

    public function __construct(Repo $repo)
    {
        $this->repo = $repo;
    }

    public function handle(string $name): bool
    {
        return $this->repo->save($name);
    }
}
