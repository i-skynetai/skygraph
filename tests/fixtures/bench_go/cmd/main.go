package main

import "example.com/proj/svc"

func main() {
	s := svc.NewService()
	_ = s.Handle("x")
}
