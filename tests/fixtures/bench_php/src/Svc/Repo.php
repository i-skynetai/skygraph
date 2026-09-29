<?php
namespace App\Svc;

class Repo
{
    public function save(string $name): bool
    {
        return $name !== '';
    }
}
